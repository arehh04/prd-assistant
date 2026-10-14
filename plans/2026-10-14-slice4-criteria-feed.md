# PRD Assistant, Slice 4: Acceptance-Criteria Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `team-task` step 1 exact, cited candidates for acceptance criteria: a bank of current-behaviour statements built from the slice 3b facts (`criteria.json`), a lookup that filters it for a task, an automatic cache outside the repo that stays fresh by git commit and working-tree fingerprint, and a drafted `team-task` step 1 for the user to apply.

**Architecture:** `criteria.py` turns `roles.json`, `form_rules.json`, `error_messages.json` (plus route and screen facts) into candidates. `lookup.py` tokenises a task, selects and ranks subjects deterministically, and renders Markdown or JSON. `criteria_cache.py` owns the state directory, the freshness fingerprint and the atomic rebuild (slice 1 pipeline, then `draft.dev_prepare`, then the bank). `bin/prd_criteria.py` is the CLI (`lookup`, `build`, `show`).

**Tech Stack:** Python 3.13 stdlib only. Read-only `git` (`rev-parse`, `status`) for the fingerprint. Builds on slices 1 to 3b.

**Spec:** `/home/arep/research/prd-assistant/design-slice4.md` (approved 2026-10-14). Parents: `design-slice3b.md`, `design-slice3.md`, `design.md`.

## Spec deviations (decided while planning; recorded in the spec's Amendments in Task 6)

1. **The `team-task` draft lives in the repo** as `docs/team-task-step1-criteria.md` (so a test can check it) and is copied to `/home/arep/research/drafts/team-task-step1-criteria.md` for the user to apply. The spec said the drafts directory only.
2. **Role names are search keys of their own.** Candidates carry `keys` (non-role) and `role_keys` (role names) as two lists; the lookup's "role words never select a subject" rule needs them apart. The spec described them as one list with a flag.
3. **Tokenising:** tokens of 2 characters are kept (so `hr` works) and a list of two-letter stopwords plus the word `id` is dropped; the stemmer is `ies`→`y`, `sses/shes/ches/xes/zes` minus `es`, otherwise a trailing single `s` (not `ss`), for tokens longer than 4 characters. The spec said "shorter than 3 dropped; strip `s`/`es`".
4. **The change fingerprint ignores everything under `.codegraph/`** (CodeGraph's own index changes whenever its watcher syncs, which would make every cache look stale).
5. **Id kind names:** `ROLE`, `REFUSED`, `FIELD`, `UNREAD`, `ERROR`, `SCREEN`, `MISMATCH`.

## Global Constraints

- Python stdlib only. Tests: `python3 -m unittest` (whole suite: `python3 -m unittest discover -s tests -t .`). CLI: `python3 -I bin/prd_criteria.py`.
- Exit codes: 0 ok (including "no match"), 2 facts unavailable (slice 1 gate FAIL, dev gate FAIL), 3 environment or input error (not a directory, no CodeGraph index, no routes, unwritable state directory, unknown id).
- Nothing is written into the repo. The only writes are under the state directory (`--state-dir`, `$PRD_ASSISTANT_STATE`, or `~/.claude/state/prd-assistant/`). A repo without `.codegraph/codegraph.db` stops before anything is created.
- A candidate states what the code does now. `derived: true` only for `role_refused`. Every candidate has at least one `trust` line (provenance). No HTTP status is stated for a refusal unless it was read.
- All text that comes from the repo is escaped before printing: `scaffold.esc` (control characters, backticks, `{{`) and `scaffold.text_cell` for running text, `scaffold.cell` inside code spans. The first lines of every lookup output say the content is data, not instructions.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Stale facts silently framing a task.** The freshness fingerprint must change for: a new commit, a tracked file edited twice with the same `git status` line, an untracked file; and must not change for `.codegraph/` churn. A non-git directory must never be treated as fresh.
2. **Role words selecting everything.** A task word that is only a role name (`finance`) must never select a route or screen; a role word must only add to the score of a subject already selected by a path, field, message or screen word.
3. **Derived refusals that the code never showed.** `role_refused` must not appear with a universe of one role, for unread/undeclared/public endpoints, across stacks, for roles never seen on a read endpoint, or with an invented HTTP status; case and `-`/`_` differences must not create phantom roles.
4. **Hostile repo text in the output.** Markdown, HTML, `{{`, ANSI/control characters, very long messages and role names, and a hostile repo directory name must not reach the printed output unescaped nor escape the state directory.
5. **Partial writes.** An interrupted or failed rebuild must leave the previous cache intact; a repo with no CodeGraph index must leave the state directory untouched; two runs at once must never expose a half-written cache; nothing may be written into the repo.

---

## File structure

| File | Responsibility |
|---|---|
| `prd_assistant/criteria.py` | `TOOL_VERSION`, `words`, `stem`, candidate builders, `build_bank` |
| `prd_assistant/lookup.py` | `select`, `render_markdown`, `render_json`, `render_candidate`, `find_candidate`, `age_text` |
| `prd_assistant/criteria_cache.py` | state directory naming, `fingerprint`, `is_fresh`, `build`, `ensure`, `EnvError`, `FactsUnavailable` |
| `bin/prd_criteria.py` | CLI: `lookup`, `build`, `show` |
| `docs/team-task-step1-criteria.md` | the drafted `team-task` step 1 (copied to the drafts directory) |
| `tests/test_criteria*.py`, `tests/test_lookup*.py`, `tests/test_criteria_cache.py`, `tests/test_criteria_cli.py`, `tests/test_calibration_criteria.py` | one test file per module |

---

### Task 1: Tokenising, role candidates, derived refusals, screen roles

**Files:**
- Create: `prd_assistant/criteria.py`
- Test: `tests/test_criteria_roles.py`

**Interfaces:**
- Consumes: `devguide._who(rec)` (wording of non-`read` role records), `roles.json` and `facts.json` shapes of slice 3b.
- Produces (`criteria.py`):
  - `TOOL_VERSION: str`, `PROVENANCE: str`
  - `stem(word) -> str`, `words(text) -> list[str]` (lowercase, camelCase split, stopwords dropped, stemmed, order kept)
  - `role_candidates(facts, roles) -> (list[dict], dict[stack, list[str]])` (`role` and `role_refused` candidates in route order, and the role universe per stack in first-seen spelling)
  - `screen_candidates(facts, roles) -> list[dict]` (`screen_roles`)
  - a candidate is `{id: None, kind, subject: {type, id, label}, text, facts, sources, derived, trust, keys, role_keys}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_criteria_roles.py
import unittest

from prd_assistant import criteria

FACTS = {"routes": [
    {"id": "r1", "method": "POST", "path": "/api/payroll/calculate", "source": "api/c.ts:5"},
    {"id": "r2", "method": "GET", "path": "/api/payroll", "source": "api/c.ts:9"},
    {"id": "r3", "method": "GET", "path": "/api/team", "source": "api/t.ts:3"},
    {"id": "r4", "method": "GET", "path": "/api/x", "source": "api/x.ts:3"},
    {"id": "r5", "method": "GET", "path": "/health", "source": "api/h.ts:1"},
    {"id": "r6", "method": "GET", "path": "/me", "source": "api/m.ts:1"}],
    "screens": [{"id": "s1", "path": "/payroll", "file": "web/r.tsx", "line": 1}]}


def rec(status="read", roles=None, **kw):
    base = {"status": status, "roles": roles, "authenticated": False, "via": [], "source": "api/c.ts:5", "stack": "nestjs"}
    base.update(kw)
    return base


ROLES = {"endpoints": {
    "r1": rec(roles=["FINANCE", "ADMIN"]),
    "r2": rec(roles=["WORKER", "finance", "admin"], source="api/c.ts:9"),
    "r3": rec("undeclared", undeclared_means="open", source="api/t.ts:3"),
    "r4": rec("not_read", reason="the role list behind @Mystery() could not be resolved", source="api/x.ts:3"),
    "r5": rec("public", source="api/h.ts:1"),
    "r6": rec(authenticated=True, source="api/m.ts:1")},
    "screens": {"s1": {"status": "read", "roles": ["FINANCE", "MANAGER"], "source": "web/nav.ts:3"}},
    "joined": {"s1": ["r1"]}, "mismatches": []}


class WordsTests(unittest.TestCase):
    def test_camel_case_plural_stopwords_and_short_words(self):
        self.assertEqual(criteria.words("PayrollsPeriod workerId"), ["payroll", "period", "worker"])
        self.assertEqual(criteria.words("Let the HR managers approve payroll"), ["hr", "manager", "approve", "payroll"])
        self.assertEqual(criteria.words("/api/v1/workforce/clock-in"), ["api", "v1", "workforce", "clock"])

    def test_stem_rules(self):
        for word, expected in (("roles", "role"), ("policies", "policy"), ("addresses", "address"), ("status", "statu"),
                               ("class", "class"), ("ids", "ids"), ("matches", "match")):
            self.assertEqual(criteria.stem(word), expected, word)


class RoleCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.cands, self.universe = criteria.role_candidates(FACTS, ROLES)
        self.by_text = {c["text"]: c for c in self.cands}

    def test_role_statements_by_status(self):
        self.assertIn("POST /api/payroll/calculate is allowed for roles FINANCE, ADMIN.", self.by_text)
        self.assertIn("GET /me is allowed for any signed-in user.", self.by_text)
        self.assertIn("GET /health is open to anyone.", self.by_text)
        undeclared = next(c for c in self.cands if c["subject"]["id"] == "r3" and c["kind"] == "role")
        self.assertIn("no declaration found", undeclared["text"])
        unread = next(c for c in self.cands if c["subject"]["id"] == "r4" and c["kind"] == "role")
        self.assertIn("could not be read", unread["text"])
        self.assertIn("@Mystery()", unread["text"])

    def test_every_candidate_has_provenance_sources_and_a_subject(self):
        for c in self.cands:
            self.assertTrue(c["trust"] and c["trust"][0] == criteria.PROVENANCE)
            self.assertTrue(c["sources"])
            self.assertIn(c["subject"]["type"], ("route", "screen"))
            self.assertIsNone(c["id"])

    def test_universe_is_the_roles_seen_on_read_endpoints_case_folded(self):
        # FINANCE, ADMIN come from r1; WORKER from r2; "finance"/"admin" on r2 fold into the first spelling
        self.assertEqual(self.universe, {"nestjs": ["FINANCE", "ADMIN", "WORKER"]})

    def test_refused_roles_are_derived_and_state_no_status_code(self):
        refused = [c for c in self.cands if c["kind"] == "role_refused"]
        self.assertEqual({(c["subject"]["id"], c["facts"]["role"]) for c in refused}, {("r1", "WORKER")})
        c = refused[0]
        self.assertTrue(c["derived"])
        self.assertEqual(c["text"], "Role WORKER is refused on POST /api/payroll/calculate.")
        self.assertNotIn("403", c["text"])
        self.assertTrue(any("derived" in t for t in c["trust"]))
        self.assertTrue(any("FINANCE, ADMIN, WORKER" in t for t in c["trust"]))

    def test_no_refusals_for_unread_undeclared_public_or_signed_in_endpoints(self):
        ids = {c["subject"]["id"] for c in self.cands if c["kind"] == "role_refused"}
        self.assertFalse(ids & {"r3", "r4", "r5", "r6"})

    def test_a_universe_of_one_role_gives_no_refusals(self):
        one = {"endpoints": {"r1": rec(roles=["ADMIN"])}, "screens": {}, "joined": {}, "mismatches": []}
        cands, universe = criteria.role_candidates({"routes": FACTS["routes"][:1], "screens": []}, one)
        self.assertEqual(universe, {"nestjs": ["ADMIN"]})
        self.assertEqual([c for c in cands if c["kind"] == "role_refused"], [])

    def test_universes_do_not_mix_across_stacks(self):
        mixed = {"endpoints": {"r1": rec(roles=["a", "b"]), "r2": rec(roles=["c", "d"], stack="fastapi"),
                               "r3": rec(roles=["a"])},
                 "screens": {}, "joined": {}, "mismatches": []}
        cands, universe = criteria.role_candidates({"routes": FACTS["routes"][:3], "screens": []}, mixed)
        refused = {(c["subject"]["id"], c["facts"]["role"]) for c in cands if c["kind"] == "role_refused"}
        self.assertEqual(universe, {"nestjs": ["a", "b"], "fastapi": ["c", "d"]})
        # r1 lists a and b (nothing left to refuse); r2 lists c and d in its own stack (nothing left);
        # r3 lists only a, so b is refused there; no role of the other stack is ever mentioned
        self.assertEqual(refused, {("r3", "b")})

    def test_notes_and_abilities_become_trust_lines(self):
        roles = {"endpoints": {"r1": rec(roles=["A", "B"], notes=["router-level dependencies are not followed"],
                                         abilities=["viewAny"])}, "screens": {}, "joined": {}, "mismatches": []}
        cands, _ = criteria.role_candidates({"routes": FACTS["routes"][:1], "screens": []}, roles)
        trust = " ".join(cands[0]["trust"])
        self.assertIn("router-level dependencies are not followed", trust)
        self.assertIn("viewAny", trust)

    def test_keys_split_path_words_from_role_words(self):
        c = self.by_text["POST /api/payroll/calculate is allowed for roles FINANCE, ADMIN."]
        self.assertIn("payroll", c["keys"])
        self.assertIn("calculate", c["keys"])
        self.assertNotIn("finance", c["keys"])
        self.assertIn("finance", c["role_keys"])


class ScreenCandidatesTests(unittest.TestCase):
    def test_screen_roles_with_join_coverage(self):
        cands = criteria.screen_candidates(FACTS, ROLES)
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual((c["kind"], c["subject"]["type"], c["text"]),
                         ("screen_roles", "screen", "Screen /payroll is shown to roles FINANCE, MANAGER."))
        self.assertTrue(any("1 of 1 screens were joined to endpoints" in t for t in c["trust"]))
        self.assertEqual(c["sources"], ["web/nav.ts:3"])

    def test_unread_screens_make_no_candidate(self):
        roles = {**ROLES, "screens": {"s1": {"status": "not_read", "roles": None, "source": "x:1", "reason": "y"}}}
        self.assertEqual(criteria.screen_candidates(FACTS, roles), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_roles 2>&1 | tail -4`
Expected: `ImportError: cannot import name 'criteria'`.

- [ ] **Step 3: Implement**

```python
# prd_assistant/criteria.py
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
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_roles 2>&1 | tail -4`
Expected: `OK` (13 tests). `test_stem_rules` documents `status` → `statu` as a known, consistent limitation (both sides of a match are stemmed the same way).

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/criteria.py tests/test_criteria_roles.py
git commit -m "feat: criteria candidates for roles, derived refusals and screens

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected: suite `OK`.

---

### Task 2: Field, request, error and mismatch candidates, and `build_bank`

**Files:**
- Modify: `prd_assistant/criteria.py`
- Test: `tests/test_criteria_bank.py`

**Interfaces:**
- Consumes: Task 1; `devguide._field_text`, `groups.group_routes`; `form_rules.json` and `error_messages.json` shapes.
- Produces:
  - `field_candidates(facts, rules) -> list` (`field` and `request_unread`)
  - `error_candidates(facts, errors) -> list`
  - `mismatch_candidates(facts, roles, rules) -> list`
  - `build_bank(facts, roles, rules, errors, cap=MAX_CANDIDATES) -> dict` with `schema_version`, `tool_version`, `candidates` (ids assigned `C-<KIND>-<NNN>`), `universe`, `counts`, `truncated`, `groups` (`[{id, key, routes}]`)
  - `KIND_ID` mapping and `MAX_CANDIDATES = 20000`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_criteria_bank.py
import unittest

from prd_assistant import criteria
from tests.test_criteria_roles import FACTS, ROLES, rec

FIELD = {"name": "period", "location": "body", "required": True, "type": "string", "min": None, "max": 7,
         "pattern": "PeriodRegex", "format": None, "one_of": None,
         "messages": ["Payroll period must be YYYY-MM"], "raw": [], "source": "pk/s.ts:3"}
RULES = {"endpoints": {
    "r1": {"source": "api/c.ts:5", "fields": [FIELD, {**FIELD, "name": "tricky", "required": None, "partial": True,
                                                       "messages": [], "source": "pk/s.ts:4", "max": None}],
           "not_read": []},
    "r2": {"source": "api/c.ts:9", "fields": [], "not_read": []},
    "r3": {"source": "api/t.ts:3", "fields": [], "not_read": ["request class X (class-validator) is not read"]}},
    "forms": {}, "counts": {},
    "mismatches": [{"screen": "s1", "endpoint": "r1", "field": "period", "kind": "max_length", "form_value": 5,
                    "endpoint_value": 7, "form_source": "web/F.tsx:4", "endpoint_source": "pk/s.ts:3"}]}
ERRORS = {"messages": [
    {"route": "r1", "status": 404, "kind": "literal", "text": "No such team", "via": "handler", "source": "api/c.ts:7"},
    {"route": "r1", "status": None, "kind": "template", "text": "Team {…} gone", "via": "helper", "helper": "h",
     "source": "api/c.ts:20", "code": "GONE"},
    {"route": "r1", "status": 403, "kind": "literal", "text": "Admin access required", "via": "guard", "source": "api/d.ts:3"},
    {"route": "r1", "status": 404, "kind": "literal", "text": "No such team", "via": "handler", "source": "api/c.ts:7"}],
    "sites": {"total": 4, "attached": 3}, "unattached": 1, "not_read": {}, "counts": {"messages": 4}}
ROLES2 = {**ROLES, "mismatches": [{"screen": "s1", "endpoint": "r1", "screen_roles": ["FINANCE", "MANAGER"],
                                   "endpoint_roles": ["FINANCE", "ADMIN"], "refused_roles": ["MANAGER"], "detail": "x"}]}


class FieldTests(unittest.TestCase):
    def setUp(self):
        self.cands = criteria.field_candidates(FACTS, RULES)

    def test_field_statement_messages_and_sources(self):
        c = next(c for c in self.cands if c["kind"] == "field" and c["facts"]["name"] == "period")
        self.assertIn("POST /api/payroll/calculate takes period (body; required, string, max 7, pattern PeriodRegex)", c["text"])
        self.assertIn("Payroll period must be YYYY-MM", c["text"])
        self.assertEqual(c["sources"], ["pk/s.ts:3"])
        self.assertIn("period", c["keys"])
        self.assertIn("payroll", c["keys"])

    def test_partial_chain_is_flagged_in_the_trust_note(self):
        c = next(c for c in self.cands if c["facts"].get("name") == "tricky")
        self.assertTrue(any("could not be parsed" in t for t in c["trust"]))
        self.assertTrue(any("hand-written input checks" in t for t in c["trust"]))

    def test_unread_requests(self):
        c = next(c for c in self.cands if c["kind"] == "request_unread")
        self.assertEqual(c["subject"]["id"], "r3")
        self.assertIn("class-validator", c["text"])


class ErrorTests(unittest.TestCase):
    def setUp(self):
        self.cands = criteria.error_candidates(FACTS, ERRORS)

    def test_statements_status_question_mark_code_and_dedupe(self):
        texts = [c["text"] for c in self.cands]
        self.assertEqual(texts.count("POST /api/payroll/calculate returns 404 'No such team'."), 1)
        self.assertIn("POST /api/payroll/calculate returns ? 'Team {…} gone' (code GONE).", texts)
        self.assertEqual(len(self.cands), 3)

    def test_trust_notes_depend_on_where_the_message_was_raised(self):
        by = {c["facts"]["via"]: c for c in self.cands}
        self.assertTrue(any("only messages in the handler" in t for t in by["handler"]["trust"]))
        self.assertTrue(any("shared by endpoints" in t for t in by["guard"]["trust"]))
        self.assertTrue(any("helper called by the handler" in t for t in by["helper"]["trust"]))


class MismatchTests(unittest.TestCase):
    def test_role_and_limit_mismatches_need_a_decision(self):
        cands = criteria.mismatch_candidates(FACTS, ROLES2, RULES)
        self.assertEqual(len(cands), 2)
        role = next(c for c in cands if "refuses" in c["text"])
        self.assertEqual(role["text"], "Screen /payroll can be opened by role MANAGER but the endpoint it calls "
                                       "(POST /api/payroll/calculate) refuses MANAGER.")
        limit = next(c for c in cands if "allows" in c["text"])
        self.assertIn("The form on screen /payroll allows 5 (max_length) in period but POST /api/payroll/calculate allows 7.",
                      limit["text"])
        for c in cands:
            self.assertEqual(c["subject"]["type"], "screen")
            self.assertTrue(any("needs a decision" in t for t in c["trust"]))
            self.assertTrue(len(c["sources"]) >= 2)
            self.assertIn("payroll", c["keys"])


class BankTests(unittest.TestCase):
    def setUp(self):
        self.bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)

    def test_ids_counts_and_header_fields(self):
        ids = [c["id"] for c in self.bank["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "C-ROLE-001")
        self.assertTrue(any(i.startswith("C-REFUSED-") for i in ids))
        self.assertTrue(any(i.startswith("C-MISMATCH-001") for i in ids))
        self.assertEqual(sum(self.bank["counts"].values()), len(ids))
        self.assertEqual((self.bank["schema_version"], self.bank["tool_version"], self.bank["truncated"]),
                         (1, criteria.TOOL_VERSION, False))
        self.assertIn("nestjs", self.bank["universe"])

    def test_candidate_order_is_routes_then_screens_then_mismatches(self):
        kinds = [c["kind"] for c in self.bank["candidates"]]
        self.assertLess(kinds.index("role"), kinds.index("screen_roles"))
        self.assertLess(kinds.index("screen_roles"), kinds.index("mismatch"))

    def test_groups_for_the_no_match_listing(self):
        self.assertTrue(all({"id", "key", "routes"} <= set(g) for g in self.bank["groups"]))

    def test_cap_truncates_and_says_so(self):
        bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS, cap=5)
        self.assertEqual(len(bank["candidates"]), 5)
        self.assertTrue(bank["truncated"])

    def test_a_repo_without_screens_or_errors_still_builds(self):
        bank = criteria.build_bank({"routes": FACTS["routes"][:1], "screens": []},
                                   {"endpoints": {"r1": rec(roles=["A"])}, "screens": {}, "joined": {}, "mismatches": []},
                                   {"endpoints": {}, "forms": {}, "mismatches": [], "counts": {}},
                                   {"messages": [], "sites": {"total": 0, "attached": 0}, "unattached": 0,
                                    "not_read": {}, "counts": {"messages": 0}})
        self.assertEqual([c["kind"] for c in bank["candidates"]], ["role"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_bank 2>&1 | tail -4`
Expected: `AttributeError: module 'prd_assistant.criteria' has no attribute 'field_candidates'`.

- [ ] **Step 3: Implement** (append to `prd_assistant/criteria.py`; add `from . import groups` and `from .devguide import _field_text, _who` at the top)

```python
MAX_CANDIDATES = 20_000
KIND_ID = {"role": "ROLE", "role_refused": "REFUSED", "field": "FIELD", "request_unread": "UNREAD",
           "error": "ERROR", "screen_roles": "SCREEN", "mismatch": "MISMATCH"}
ERROR_TRUST = "only messages in the handler, its guards and the functions it calls directly are read; messages raised deeper are not included"


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
        srcs = [(roles["screens"].get(m["screen"]) or {}).get("source"), (roles["endpoints"].get(m["endpoint"]) or {}).get("source")]
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
    counters, counts = {}, {}
    for c in ordered:
        counters[c["kind"]] = counters.get(c["kind"], 0) + 1
        counts[c["kind"]] = counters[c["kind"]]
        c["id"] = f"C-{KIND_ID[c['kind']]}-{counters[c['kind']]:03d}"
    return {"schema_version": 1, "tool_version": TOOL_VERSION, "candidates": ordered, "universe": universe,
            "counts": counts, "truncated": truncated,
            "groups": [{"id": g["id"], "key": g["key"], "routes": len(g["routes"])}
                       for g in groups.group_routes(facts["routes"])]}
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_bank tests.test_criteria_roles 2>&1 | tail -4`
Expected: `OK` (24 tests).

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/criteria.py tests/test_criteria_bank.py
git commit -m "feat: criteria bank (fields, unread requests, errors, mismatches, ids, caps)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The lookup (select, rank, render)

**Files:**
- Create: `prd_assistant/lookup.py`
- Test: `tests/test_lookup.py`

**Interfaces:**
- Consumes: `criteria.words`, a bank from `criteria.build_bank`, `scaffold.{esc,cell,text_cell}`.
- Produces (`lookup.py`):
  - `select(bank, text, max_subjects=5, max_candidates=60) -> {"tokens", "matched", "subjects": [{"subject","score","candidates"}], "omitted", "subjects_found"}`
  - `age_text(built_at, now=None) -> str`
  - `render_markdown(sel, meta, bank) -> str`; `render_json(sel, meta) -> dict`
  - `find_candidate(bank, cid) -> dict | None`; `render_candidate(c, meta) -> str`
  - `meta` is `{repo, head, built_at, changed, git, cache}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lookup.py
import datetime
import unittest

from prd_assistant import criteria, lookup
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_roles import rec

FACTS3 = {**FACTS, "routes": FACTS["routes"] + [{"id": "r7", "method": "GET", "path": "/api/invoices", "source": "api/i.ts:1"}]}
ROLES3 = {**ROLES2, "endpoints": {**ROLES2["endpoints"], "r7": rec(roles=["FINANCE"], source="api/i.ts:1")}}
BANK = criteria.build_bank(FACTS3, ROLES3, RULES, ERRORS)
META = {"repo": "/work/demo", "head": "abcdef1234567", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0, "git": True,
        "cache": "/state/demo-1234"}
NOW = datetime.datetime(2026, 10, 14, 10, 3, tzinfo=datetime.timezone.utc)


def labels(sel):
    return [s["subject"]["label"] for s in sel["subjects"]]


class SelectTests(unittest.TestCase):
    def test_path_and_field_words_select_and_rank_subjects(self):
        sel = lookup.select(BANK, "let finance managers calculate payroll")
        self.assertTrue(sel["matched"])
        self.assertEqual(labels(sel)[0], "POST /api/payroll/calculate")
        self.assertIn("GET /api/payroll", labels(sel))
        self.assertIn("screen /payroll", labels(sel))
        self.assertNotIn("GET /api/team", labels(sel))

    def test_role_words_alone_never_select_a_subject(self):
        sel = lookup.select(BANK, "finance manager")   # both appear only in role lists, never in a path, field or message
        self.assertFalse(sel["matched"])
        self.assertNotIn("GET /api/invoices", labels(sel))

    def test_role_words_add_half_a_point_to_a_subject_already_selected(self):
        plain = {s["subject"]["label"]: s["score"] for s in lookup.select(BANK, "payroll")["subjects"]}
        with_role = {s["subject"]["label"]: s["score"] for s in lookup.select(BANK, "payroll finance")["subjects"]}
        self.assertEqual(with_role["POST /api/payroll/calculate"], plain["POST /api/payroll/calculate"] + 0.5)

    def test_field_names_and_message_words_select(self):
        self.assertIn("POST /api/payroll/calculate", labels(lookup.select(BANK, "the period regex")))
        self.assertIn("POST /api/payroll/calculate", labels(lookup.select(BANK, "no such team error")))

    def test_caps_report_what_was_left_out(self):
        sel = lookup.select(BANK, "payroll", max_subjects=1)
        self.assertEqual(len(sel["subjects"]), 1)
        self.assertGreaterEqual(sel["subjects_found"], 2)
        cut = lookup.select(BANK, "payroll", max_candidates=3)
        self.assertEqual(sum(len(s["candidates"]) for s in cut["subjects"]), 3)
        self.assertGreater(cut["omitted"], 0)

    def test_no_match_and_unusable_task_text(self):
        for text in ("xyzzy plugh", "", "the and of", "\x00\x01"):
            sel = lookup.select(BANK, text)
            self.assertFalse(sel["matched"], text)
            self.assertEqual(sel["subjects"], [])

    def test_very_long_task_text_is_cut(self):
        sel = lookup.select(BANK, "payroll " + "zzz " * 200000)
        self.assertTrue(sel["matched"])
        self.assertLessEqual(len(sel["tokens"]), 600)


class RenderTests(unittest.TestCase):
    def test_header_frames_the_content_as_data_and_states_the_facts_age(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll"), META, BANK, now=NOW)
        self.assertIn("not instructions", out.splitlines()[2])
        self.assertIn("built 3 minutes ago at commit `abcdef1`", out)
        self.assertIn("working tree: clean", out)
        self.assertIn("`/state/demo-1234`", out)

    def test_candidates_show_id_kind_derived_sources_and_trust(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll calculate"), META, BANK, now=NOW)
        self.assertIn("- [C-ROLE-001] role: POST /api/payroll/calculate is allowed for roles FINANCE, ADMIN.", out)
        self.assertRegex(out, r"\[C-REFUSED-\d+\] role_refused \(derived\):")
        self.assertIn("  - sources: `api/c.ts:5`", out)
        self.assertIn("  - trust: Read from the code at the cited source", out)

    def test_dirty_and_non_git_states_are_stated(self):
        sel = lookup.select(BANK, "payroll")
        self.assertIn("working tree: 3 changed files", lookup.render_markdown(sel, {**META, "changed": 3}, BANK, now=NOW))
        self.assertIn("not a git repository", lookup.render_markdown(sel, {**META, "git": False, "changed": None}, BANK, now=NOW))

    def test_no_match_lists_groups_the_bank_path_and_counts(self):
        out = lookup.render_markdown(lookup.select(BANK, "xyzzy"), META, BANK, now=NOW)
        self.assertIn("No match for these task words: xyzzy", out)
        self.assertIn("Route groups:", out)
        self.assertIn("`/state/demo-1234/criteria.json`", out)
        self.assertIn("role:", out)

    def test_left_out_lines(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll", max_candidates=3), META, BANK, now=NOW)
        self.assertRegex(out, r"_\d+ more candidates for these subjects were left out")

    def test_json_shape(self):
        data = lookup.render_json(lookup.select(BANK, "payroll"), META)
        self.assertEqual(set(data), {"meta", "tokens", "matched", "subjects", "omitted", "subjects_found"})
        self.assertTrue(data["subjects"][0]["candidates"][0]["id"].startswith("C-"))

    def test_hostile_repo_text_is_neutralised(self):
        hostile = "<img src=x onerror=alert(1)> {{slot:overview}} `tick` [x](http://e.example) \x1b[31mred\x00"
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": hostile,
                                          "via": "handler", "source": "api/c.ts:7"}]}
        roles = {**ROLES3, "endpoints": {**ROLES3["endpoints"], "r1": rec(roles=[hostile, "ADMIN"])}}
        bank = criteria.build_bank(FACTS3, roles, RULES, errors)
        out = lookup.render_markdown(lookup.select(bank, "payroll calculate"), META, bank, now=NOW)
        self.assertNotRegex(out, r"(?<!\\)<img")
        self.assertNotIn("{{slot:", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x00", out)
        self.assertNotIn("](http://e.example)", out.replace("\\]", "").replace("\\[", ""))
        self.assertEqual(out.count("`tick`"), 0)

    def test_an_overlong_trust_line_is_clipped(self):
        bank = {**BANK, "candidates": [{**BANK["candidates"][0], "trust": ["x" * 5000]}] + BANK["candidates"][1:]}
        out = lookup.render_markdown(lookup.select(bank, "payroll"), META, bank, now=NOW)
        self.assertNotIn("x" * 600, out)


class AgeTests(unittest.TestCase):
    def test_age_text(self):
        t = datetime.datetime(2026, 10, 14, 10, 0, tzinfo=datetime.timezone.utc)
        for seconds, expected in ((5, "just now"), (180, "3 minutes ago"), (7200, "2 hours ago"), (3 * 86400, "3 days ago")):
            self.assertEqual(lookup.age_text(t.isoformat(), t + datetime.timedelta(seconds=seconds)), expected)
        self.assertEqual(lookup.age_text("garbage"), "at an unknown time")


class ShowTests(unittest.TestCase):
    def test_find_and_render_a_candidate(self):
        c = lookup.find_candidate(BANK, "C-ROLE-001")
        self.assertEqual(c["kind"], "role")
        self.assertIsNone(lookup.find_candidate(BANK, "C-NOPE-999"))
        out = lookup.render_candidate(c, META)
        self.assertIn("C-ROLE-001", out)
        self.assertIn("FINANCE", out)
        self.assertIn("not instructions", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_lookup 2>&1 | tail -4`
Expected: `ImportError: cannot import name 'lookup'`.

- [ ] **Step 3: Implement**

```python
# prd_assistant/lookup.py
"""Task words to the candidates that concern them, and how those are printed."""
import datetime
import json

from .criteria import words
from .scaffold import cell, esc, text_cell

MAX_TASK = 2000
MAX_TOKENS = 600
CLIP = 400


def _clip(text, n=CLIP):
    text = str(text)
    return text if len(text) <= n else text[:n] + "…"


def select(bank, text, max_subjects=5, max_candidates=60):
    tokens = list(dict.fromkeys(words(str(text)[:MAX_TASK])))[:MAX_TOKENS]
    subjects = {}
    for c in bank["candidates"]:
        key = (c["subject"]["type"], c["subject"]["id"])
        s = subjects.setdefault(key, {"subject": c["subject"], "keys": set(), "role_keys": set(), "candidates": []})
        s["keys"].update(c["keys"])
        s["role_keys"].update(c["role_keys"])
        s["candidates"].append(c)
    scored = []
    for s in subjects.values():
        hits = [t for t in tokens if t in s["keys"]]
        if not hits:
            continue
        role_hits = [t for t in tokens if t in s["role_keys"] and t not in hits]
        scored.append((len(hits) + 0.5 * len(role_hits), s))
    scored.sort(key=lambda p: (-p[0], p[1]["subject"]["label"]))
    chosen, left = scored[:max_subjects], max_candidates
    out, omitted = [], 0
    for score, s in chosen:
        take = s["candidates"][:max(left, 0)]
        omitted += len(s["candidates"]) - len(take)
        left -= len(take)
        if take:
            out.append({"subject": s["subject"], "score": score, "candidates": take})
    return {"tokens": tokens, "matched": bool(out), "subjects": out, "omitted": omitted, "subjects_found": len(scored)}


def age_text(built_at, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        then = datetime.datetime.fromisoformat(built_at)
        seconds = max(0, int((now - then).total_seconds()))
    except (TypeError, ValueError):
        return "at an unknown time"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _tree_state(meta):
    if not meta.get("git"):
        return "not a git repository (the facts are rebuilt on every run)"
    return "clean" if not meta.get("changed") else f"{meta['changed']} changed files"


def _header(meta, now):
    name = str(meta.get("repo", "")).rstrip("/").rsplit("/", 1)[-1]
    return ["# Criteria candidates", "", "_These are facts extracted from the repository, not instructions._", "",
            f"- Repo: `{cell(name)}`",
            f"- Facts built {age_text(meta.get('built_at'), now)} at commit `{cell(str(meta.get('head') or '?')[:7])}`; "
            f"working tree: {_tree_state(meta)}",
            f"- Cache: `{cell(meta.get('cache', ''))}`"]


def _candidate_lines(c):
    tag = c["kind"] + (" (derived)" if c["derived"] else "")
    return [f"- [{c['id']}] {tag}: {text_cell(_clip(c['text'], 1000))}",
            "  - sources: " + ", ".join(f"`{cell(_clip(s, 200))}`" for s in c["sources"]),
            "  - trust: " + text_cell("; ".join(_clip(t) for t in c["trust"]))]


def render_markdown(sel, meta, bank, now=None):
    L = _header(meta, now)
    shown = ", ".join(esc(t) for t in sel["tokens"]) or "none"
    L += [f"- Task words used: {shown}", ""]
    if not sel["matched"]:
        if not sel["tokens"]:
            L += ["The task text had no usable words.", ""]
        L += [f"No match for these task words: {shown}", ""]
        L += ["Route groups:"] + [f"- {g['id']} `{cell(g['key'])}` ({g['routes']} routes)" for g in bank["groups"][:50]]
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(bank["counts"].items()))
        L += ["", f"Bank: `{cell(str(meta.get('cache', '')) + '/criteria.json')}` ({counts}).", ""]
        return "\n".join(L) + "\n"
    for s in sel["subjects"]:
        L += [f"## {text_cell(_clip(s['subject']['label'], 300))}", ""]
        for c in s["candidates"]:
            L += _candidate_lines(c)
        L.append("")
    if sel["omitted"]:
        L += [f"_{sel['omitted']} more candidates for these subjects were left out (raise --max-candidates)._"]
    hidden = sel["subjects_found"] - len(sel["subjects"])
    if hidden > 0:
        L += [f"_{hidden} more matching subjects were not shown (raise --max-subjects)._"]
    return "\n".join(L) + "\n"


def render_json(sel, meta):
    return {"meta": meta, "tokens": sel["tokens"], "matched": sel["matched"], "subjects": sel["subjects"],
            "omitted": sel["omitted"], "subjects_found": sel["subjects_found"]}


def find_candidate(bank, cid):
    return next((c for c in bank["candidates"] if c["id"] == cid), None)


def render_candidate(c, meta, now=None):
    L = _header(meta, now) + [""]
    L += [f"## {c['id']} ({c['kind']}{', derived' if c['derived'] else ''})", "",
          f"Subject: {text_cell(_clip(c['subject']['label'], 300))}", "", text_cell(c["text"]), "", "Facts:", "",
          esc(json.dumps(c["facts"], ensure_ascii=False, indent=2, default=str)[:2000]), "",
          "Sources: " + ", ".join(f"`{cell(s)}`" for s in c["sources"]), "",
          "Trust:"] + [f"- {text_cell(_clip(t))}" for t in c["trust"]]
    return "\n".join(L) + "\n"
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_lookup 2>&1 | tail -4`
Expected: `OK` (19 tests). In `render_candidate` the facts block is plain text after `esc` (no code fence), so a hostile value cannot close a fence.

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/lookup.py tests/test_lookup.py
git commit -m "feat: criteria lookup (select, rank, render, show)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The cache (state directory, fingerprint, freshness, atomic rebuild)

**Files:**
- Create: `prd_assistant/criteria_cache.py`
- Test: `tests/test_criteria_cache.py`

**Interfaces:**
- Consumes: `pipeline.run`, `pipeline.write_outputs`, `draft.dev_prepare`, `draft.GateFailed`, `cgdb.VersionError`, `criteria.build_bank`, `criteria.TOOL_VERSION`.
- Produces (`criteria_cache.py`):
  - `class EnvError(RuntimeError)` (exit 3), `class FactsUnavailable(RuntimeError)` (exit 2)
  - `state_root(override=None) -> Path`, `repo_dir_name(repo) -> str`
  - `fingerprint(repo) -> {"git", "head", "dirty", "changed"}`
  - `is_fresh(meta, fp) -> bool`
  - `build(repo, root, fp) -> (cache_dir, meta)`
  - `ensure(repo, state_dir=None, force=False) -> (cache_dir, meta, rebuilt)`
  - `load_bank(cache_dir) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_criteria_cache.py
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES

FACTS_FULL = {**FACTS, "meta": {"indexed_at_commit": "cafe123"}}
OK_RESULT = {"verdict": "PASS", "checks": []}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repo(tmp, name="demo", with_index=True):
    repo = Path(tmp) / name
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    if with_index:
        (repo / ".codegraph").mkdir()
        (repo / ".codegraph" / "codegraph.db").write_text("db")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def fake_write_outputs(out, facts, result):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts))
    (out / "gate.json").write_text(json.dumps(result))


def fake_dev_prepare(repo, out, today=None):
    dev = Path(out) / "dev"
    dev.mkdir(exist_ok=True)
    for name, data in (("roles.json", ROLES2), ("form_rules.json", RULES), ("error_messages.json", ERRORS)):
        (dev / name).write_text(json.dumps(data))
    return {}


class PatchedPipeline:
    """Replaces the heavy slice 1 and 3b steps with the synthetic facts used by the other tests."""

    def __enter__(self):
        self.patches = [mock.patch("prd_assistant.criteria_cache.pipeline.run", return_value=(FACTS_FULL, OK_RESULT)),
                        mock.patch("prd_assistant.criteria_cache.pipeline.write_outputs", side_effect=fake_write_outputs),
                        mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=fake_dev_prepare)]
        self.run = self.patches[0].start()
        for p in self.patches[1:]:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class NamingTests(unittest.TestCase):
    def test_state_root_precedence(self):
        with mock.patch.dict(os.environ, {"PRD_ASSISTANT_STATE": "/env/state"}):
            self.assertEqual(criteria_cache.state_root("/given"), Path("/given"))
            self.assertEqual(criteria_cache.state_root(), Path("/env/state"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(criteria_cache.state_root(), Path.home() / ".claude" / "state" / "prd-assistant")

    def test_hostile_directory_names_cannot_escape_or_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = {}
            for raw in ("a b$c;rm -rf", "...", "ünï", "x" * 200):
                d = Path(tmp) / raw
                d.mkdir()
                name = criteria_cache.repo_dir_name(d)
                names[raw] = name
                self.assertRegex(name, r"^[A-Za-z0-9._-]{1,40}-[0-9a-f]{8}$")
                self.assertNotIn("/", name)
                self.assertFalse(name.startswith("."))
            self.assertEqual(len(set(names.values())), 4)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)

    def test_clean_repo(self):
        fp = criteria_cache.fingerprint(self.repo)
        self.assertEqual((fp["git"], fp["changed"]), (True, 0))
        self.assertRegex(fp["head"], r"^[0-9a-f]{40}$")

    def test_codegraph_churn_is_ignored(self):
        before = criteria_cache.fingerprint(self.repo)
        (self.repo / ".codegraph" / "codegraph.db").write_text("a much longer database")
        (self.repo / ".codegraph" / "daemon.log").write_text("new")
        self.assertEqual(criteria_cache.fingerprint(self.repo), before)

    def test_new_commit_untracked_file_and_double_edit_all_change_it(self):
        base = criteria_cache.fingerprint(self.repo)
        (self.repo / "new.py").write_text("y = 2\n")
        untracked = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(untracked["dirty"], base["dirty"])
        self.assertEqual(untracked["changed"], 1)
        (self.repo / "a.py").write_text("x = 22\n")
        once = criteria_cache.fingerprint(self.repo)
        (self.repo / "a.py").write_text("x = 3333\n")   # same ' M a.py' status line, different content
        twice = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(once["dirty"], twice["dirty"])
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        after = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(after["head"], base["head"])
        self.assertEqual(after["changed"], 0)

    def test_a_directory_that_is_not_a_git_repository(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        fp = criteria_cache.fingerprint(plain)
        self.assertEqual((fp["git"], fp["head"], fp["dirty"]), (False, None, None))
        self.assertFalse(criteria_cache.is_fresh({"tool_version": criteria.TOOL_VERSION, "schema_version": 1,
                                                  "head": None, "dirty": None}, fp))


class FreshnessTests(unittest.TestCase):
    def test_is_fresh_matrix(self):
        fp = {"git": True, "head": "h", "dirty": "d", "changed": 0}
        good = {"tool_version": criteria.TOOL_VERSION, "schema_version": 1, "head": "h", "dirty": "d"}
        self.assertTrue(criteria_cache.is_fresh(good, fp))
        for change in ({"tool_version": "0"}, {"schema_version": 2}, {"head": "x"}, {"dirty": "x"}):
            self.assertFalse(criteria_cache.is_fresh({**good, **change}, fp), change)
        self.assertFalse(criteria_cache.is_fresh(None, fp))


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def test_first_call_builds_second_reuses_new_commit_rebuilds(self):
        with PatchedPipeline() as p:
            cache, meta, rebuilt = criteria_cache.ensure(self.repo, self.state)
            self.assertTrue(rebuilt)
            for name in ("criteria.json", "meta.json", "facts.json", "dev/roles.json"):
                self.assertTrue((cache / name).is_file(), name)
            self.assertEqual(meta["codegraph_commit"], "cafe123")
            self.assertEqual(criteria_cache.load_bank(cache)["tool_version"], criteria.TOOL_VERSION)
            self.assertEqual([x.name for x in self.state.iterdir() if x.name.startswith(".build-")], [])
            _, _, again = criteria_cache.ensure(self.repo, self.state)
            self.assertFalse(again)
            self.assertEqual(p.run.call_count, 1)
            (self.repo / "b.py").write_text("z = 1\n")
            _, _, third = criteria_cache.ensure(self.repo, self.state)
            self.assertTrue(third)
            self.assertEqual(p.run.call_count, 2)

    def test_force_rebuilds(self):
        with PatchedPipeline() as p:
            criteria_cache.ensure(self.repo, self.state)
            criteria_cache.ensure(self.repo, self.state, force=True)
            self.assertEqual(p.run.call_count, 2)

    def test_a_non_git_directory_is_rebuilt_every_time(self):
        plain = Path(self.tmp.name) / "plain"
        (plain / ".codegraph").mkdir(parents=True)
        (plain / ".codegraph" / "codegraph.db").write_text("db")
        with PatchedPipeline() as p:
            _, meta, _ = criteria_cache.ensure(plain, self.state)
            criteria_cache.ensure(plain, self.state)
            self.assertEqual(p.run.call_count, 2)
            self.assertFalse(meta["git"])

    def test_no_codegraph_index_writes_nothing(self):
        bare = make_repo(self.tmp.name, "bare", with_index=False)
        with PatchedPipeline():
            with self.assertRaises(criteria_cache.EnvError) as ctx:
                criteria_cache.ensure(bare, self.state)
        self.assertIn("CodeGraph", str(ctx.exception))
        self.assertFalse(self.state.exists())

    def test_not_a_directory(self):
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.ensure(Path(self.tmp.name) / "nope", self.state)

    def test_failed_rebuild_keeps_the_previous_cache(self):
        with PatchedPipeline():
            cache, meta, _ = criteria_cache.ensure(self.repo, self.state)
        before = (cache / "criteria.json").read_text()
        with mock.patch("prd_assistant.criteria_cache.pipeline.run", side_effect=OSError("disk went away")):
            with self.assertRaises(criteria_cache.EnvError):
                criteria_cache.ensure(self.repo, self.state, force=True)
        self.assertEqual((cache / "criteria.json").read_text(), before)
        self.assertEqual([x.name for x in self.state.iterdir() if x.name.startswith(".build-")], [])

    def test_gate_failure_is_facts_unavailable(self):
        with PatchedPipeline() as p:
            p.run.return_value = (FACTS_FULL, {"verdict": "FAIL", "checks": []})
            with self.assertRaises(criteria_cache.FactsUnavailable):
                criteria_cache.ensure(self.repo, self.state)
        self.assertEqual([x.name for x in self.state.iterdir()], [])

    def test_dev_gate_failure_and_no_routes(self):
        from prd_assistant import draft
        with PatchedPipeline():
            with mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=draft.GateFailed("dev gate is FAIL")):
                with self.assertRaises(criteria_cache.FactsUnavailable):
                    criteria_cache.ensure(self.repo, self.state)
            with mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=ValueError("no routes were extracted")):
                with self.assertRaises(criteria_cache.EnvError):
                    criteria_cache.ensure(self.repo, self.state)

    def test_unwritable_state_directory(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("a file, not a directory")
        with PatchedPipeline():
            with self.assertRaises(criteria_cache.EnvError):
                criteria_cache.ensure(self.repo, blocker / "state")

    def test_nothing_is_written_into_the_repo(self):
        before = sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if ".git" not in p.parts)
        with PatchedPipeline():
            criteria_cache.ensure(self.repo, self.state)
        after = sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if ".git" not in p.parts)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_cache 2>&1 | tail -4`
Expected: `ImportError: cannot import name 'criteria_cache'`.

- [ ] **Step 3: Implement**

```python
# prd_assistant/criteria_cache.py
"""The criteria cache: where the facts live, when they are stale, and how they are rebuilt without half-writes."""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import cgdb, criteria, draft, pipeline

IGNORED_PREFIXES = (".codegraph/",)   # CodeGraph's own index changes whenever its watcher syncs


class EnvError(RuntimeError):
    """The environment or input is unusable (exit 3)."""


class FactsUnavailable(RuntimeError):
    """The facts cannot be trusted or produced (exit 2)."""


def state_root(override=None):
    if override:
        return Path(override)
    env = os.environ.get("PRD_ASSISTANT_STATE")
    return Path(env) if env else Path.home() / ".claude" / "state" / "prd-assistant"


def repo_dir_name(repo):
    path = Path(repo).resolve()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name).strip("._") or "repo"
    return f"{name[:40]}-{hashlib.sha256(str(path).encode()).hexdigest()[:8]}"


def _git(repo, *args):
    """Read-only git (never takes optional locks). None when git is missing or the command fails."""
    try:
        run = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout if run.returncode == 0 else None


def fingerprint(repo):
    repo = Path(repo).resolve()
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "-uall")
    if head is None or status is None:
        return {"git": False, "head": None, "dirty": None, "changed": None}
    digest, changed = hashlib.sha256(), 0
    for line in status.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if path.startswith(IGNORED_PREFIXES):
            continue
        changed += 1
        try:
            st = (repo / path).stat()
            stamp = f"{st.st_size}:{st.st_mtime_ns}"
        except OSError:
            stamp = "missing"
        digest.update(f"{line}\0{stamp}\0".encode())
    return {"git": True, "head": head.strip(), "dirty": digest.hexdigest(), "changed": changed}


def is_fresh(meta, fp):
    return bool(fp["git"] and meta and meta.get("tool_version") == criteria.TOOL_VERSION
                and meta.get("schema_version") == 1 and meta.get("head") == fp["head"]
                and meta.get("dirty") == fp["dirty"])


def _read_meta(cache):
    try:
        return json.loads((Path(cache) / "meta.json").read_text())
    except (OSError, ValueError):
        return None


def load_bank(cache):
    return json.loads((Path(cache) / "criteria.json").read_text())


def _swap(work, final):
    old = None
    if final.exists():
        old = final.with_name(f"{final.name}.old-{os.getpid()}")
        os.rename(final, old)
    try:
        os.rename(work, final)
    except OSError:
        if old is not None:
            os.rename(old, final)   # put the previous cache back
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def build(repo, root, fp):
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    if not (repo / ".codegraph" / "codegraph.db").is_file():
        raise EnvError(f"{repo} has no CodeGraph index (.codegraph/codegraph.db); run `codegraph init` there first. "
                       "Nothing was built.")
    try:
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    except OSError as exc:
        raise EnvError(f"cannot create the state directory {root}: {exc}") from exc
    final = root / repo_dir_name(repo)
    try:
        facts, result = pipeline.run(repo)
        pipeline.write_outputs(work, facts, result)
        if result["verdict"] == "FAIL":
            raise FactsUnavailable("the slice 1 gate is FAIL, so the facts cannot be trusted; "
                                   "run bin/prd_facts.py on the repo to see why")
        draft.dev_prepare(repo, work)
        dev = work / "dev"
        roles, rules, errors = (json.loads((dev / n).read_text())
                                for n in ("roles.json", "form_rules.json", "error_messages.json"))
        bank = criteria.build_bank(facts, roles, rules, errors)
        meta = {"schema_version": 1, "tool_version": criteria.TOOL_VERSION, "repo": str(repo), "head": fp["head"],
                "dirty": fp["dirty"], "changed": fp["changed"], "git": fp["git"],
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "codegraph_commit": facts.get("meta", {}).get("indexed_at_commit"), "counts": bank["counts"],
                "routes": len(facts["routes"]), "screens": len(facts["screens"])}
        (work / "criteria.json").write_text(json.dumps(bank, indent=1, ensure_ascii=False))
        (work / "meta.json").write_text(json.dumps(meta, indent=1))
        _swap(work, final)
    except draft.GateFailed as exc:
        raise FactsUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise EnvError(str(exc)) from exc
    except (cgdb.VersionError, FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        raise EnvError(str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)   # a no-op after a successful swap
    return final, meta


def ensure(repo, state_dir=None, force=False):
    repo = Path(repo)
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    root = state_root(state_dir)
    final = root / repo_dir_name(repo)
    fp = fingerprint(repo)
    meta = _read_meta(final)
    if not force and is_fresh(meta, fp):
        return final, meta, False
    final, meta = build(repo, root, fp)
    return final, meta, True
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_cache 2>&1 | tail -4`
Expected: `OK` (17 tests). If `test_failed_rebuild_keeps_the_previous_cache` fails because `FactsUnavailable` raised inside the `try` also triggers `finally`, that is correct; the check is that `criteria.json` is untouched and no `.build-*` directory remains.

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/criteria_cache.py tests/test_criteria_cache.py
git commit -m "feat: criteria cache (state directory, git fingerprint, atomic rebuild)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The CLI (`bin/prd_criteria.py`)

**Files:**
- Create: `bin/prd_criteria.py`
- Test: `tests/test_criteria_cli.py`

**Interfaces:**
- Consumes: `criteria_cache.ensure/load_bank/EnvError/FactsUnavailable`, `lookup.*`.
- Produces: `main(argv=None) -> int`; commands `lookup REPO TASK [--max-subjects N] [--max-candidates N] [--json] [--state-dir DIR]`, `build REPO [--state-dir DIR]`, `show REPO --id ID [--json] [--state-dir DIR]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_criteria_cli.py
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prd_criteria", ROOT / "bin" / "prd_criteria.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def make_cache(tmp):
    cache = Path(tmp) / "cache"
    cache.mkdir()
    bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
    (cache / "criteria.json").write_text(json.dumps(bank))
    meta = {"repo": "/work/demo", "head": "abcdef1234", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0,
            "git": True, "counts": bank["counts"]}
    (cache / "meta.json").write_text(json.dumps(meta))
    return cache, meta


def run(argv, ensure=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with mock.patch("prd_assistant.criteria_cache.ensure", **({"side_effect": ensure} if callable(ensure) else {"return_value": ensure})):
            code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache, self.meta = make_cache(self.tmp.name)
        self.ok = (self.cache, self.meta, False)

    def test_lookup_markdown(self):
        code, out, err = run(["lookup", "/work/demo", "calculate payroll"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("not instructions", out)
        self.assertIn("[C-ROLE-001]", out)
        self.assertEqual(err, "")

    def test_lookup_json_and_caps(self):
        code, out, _ = run(["lookup", "/work/demo", "payroll", "--json", "--max-subjects", "1"], self.ok)
        data = json.loads(out)
        self.assertEqual((code, len(data["subjects"])), (0, 1))
        self.assertEqual(data["meta"]["cache"], str(self.cache))

    def test_no_match_is_exit_zero(self):
        code, out, _ = run(["lookup", "/work/demo", "xyzzy"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("No match for these task words", out)

    def test_a_rebuild_is_announced_on_stderr_only(self):
        code, out, err = run(["lookup", "/work/demo", "payroll"], (self.cache, self.meta, True))
        self.assertEqual(code, 0)
        self.assertIn("rebuilt", err)
        self.assertNotIn("rebuilt", out)

    def test_show(self):
        code, out, _ = run(["show", "/work/demo", "--id", "C-ROLE-001"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("C-ROLE-001", out)
        code, _, err = run(["show", "/work/demo", "--id", "C-NOPE-999"], self.ok)
        self.assertEqual(code, 3)
        self.assertIn("C-NOPE-999", err)

    def test_build_prints_the_cache_path_commit_and_counts(self):
        code, out, _ = run(["build", "/work/demo"], (self.cache, self.meta, True))
        self.assertEqual(code, 0)
        self.assertIn(str(self.cache), out)
        self.assertIn("abcdef1", out)
        self.assertIn("role:", out)

    def test_exit_codes_for_unavailable_facts_and_environment_errors(self):
        def boom(exc):
            def raiser(*a, **k):
                raise exc
            return raiser
        code, _, err = run(["lookup", "/work/demo", "x"], boom(criteria_cache.FactsUnavailable("gate FAIL")))
        self.assertEqual((code, "gate FAIL" in err), (2, True))
        code, _, err = run(["lookup", "/work/demo", "x"], boom(criteria_cache.EnvError("no CodeGraph index")))
        self.assertEqual((code, "no CodeGraph index" in err), (3, True))

    def test_force_is_only_used_by_build(self):
        with mock.patch("prd_assistant.criteria_cache.ensure", return_value=self.ok) as ensure:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["lookup", "/work/demo", "payroll", "--state-dir", "/s"])
                cli.main(["build", "/work/demo"])
        self.assertFalse(ensure.call_args_list[0].kwargs["force"])
        self.assertTrue(ensure.call_args_list[1].kwargs["force"])
        self.assertEqual(ensure.call_args_list[0].args[1], "/s")

    def test_script_runs_under_isolated_mode(self):
        import subprocess
        import sys
        run = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "prd_criteria.py"), "--help"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertIn("lookup", run.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_cli 2>&1 | tail -4`
Expected: `FileNotFoundError` for `bin/prd_criteria.py`.

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Acceptance-criteria candidates from the facts of a repo, for team-task step 1.

Usage:
  python3 -I bin/prd_criteria.py lookup REPO "task words" [--max-subjects N] [--max-candidates N] [--json] [--state-dir DIR]
  python3 -I bin/prd_criteria.py build  REPO [--state-dir DIR]
  python3 -I bin/prd_criteria.py show   REPO --id C-ROLE-014 [--json] [--state-dir DIR]
Exit codes: 0 ok (including no match), 2 facts unavailable, 3 environment or input error.
The facts are cached under ~/.claude/state/prd-assistant/ and rebuilt when the repo's commit or working tree changed.
"""
import argparse
import json
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import criteria_cache, lookup  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("lookup", "build", "show"):
        p = sub.add_parser(name)
        p.add_argument("repo")
        p.add_argument("--state-dir")
        if name == "lookup":
            p.add_argument("task")
            p.add_argument("--max-subjects", type=int, default=5)
            p.add_argument("--max-candidates", type=int, default=60)
        if name != "build":
            p.add_argument("--json", action="store_true")
        if name == "show":
            p.add_argument("--id", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        cache, meta, rebuilt = criteria_cache.ensure(args.repo, args.state_dir, force=(args.command == "build"))
        bank = criteria_cache.load_bank(cache)
    except criteria_cache.FactsUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (criteria_cache.EnvError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if rebuilt:
        print("note: the facts for this repo were rebuilt", file=sys.stderr)
    info = {"repo": meta.get("repo"), "head": meta.get("head"), "built_at": meta.get("built_at"),
            "changed": meta.get("changed"), "git": meta.get("git"), "cache": str(cache)}
    if args.command == "build":
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(bank["counts"].items()))
        print(f"cache: {cache}\ncommit: {str(meta.get('head') or '?')[:7]}\ncandidates: {counts}")
        return 0
    if args.command == "show":
        c = lookup.find_candidate(bank, args.id)
        if c is None:
            print(f"error: no candidate with id {args.id!r} in this cache (ids change when the code changes)", file=sys.stderr)
            return 3
        print(json.dumps({"meta": info, "candidate": c}, indent=1, ensure_ascii=False) if args.json
              else lookup.render_candidate(c, info), end="")
        return 0
    sel = lookup.select(bank, args.task, args.max_subjects, args.max_candidates)
    if args.json:
        print(json.dumps(lookup.render_json(sel, info), indent=1, ensure_ascii=False))
    else:
        print(lookup.render_markdown(sel, info, bank), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && chmod +x bin/prd_criteria.py && python3 -m unittest tests.test_criteria_cli 2>&1 | tail -4`
Expected: `OK` (9 tests).

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add bin/prd_criteria.py tests/test_criteria_cli.py
git commit -m "feat: prd_criteria CLI (lookup, build, show)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Hardening, the `team-task` draft, calibration on the three repos, golden tests, notes and spec amendments

**Files:**
- Create: `tests/test_criteria_hardening.py`, `tests/test_calibration_criteria.py`, `docs/team-task-step1-criteria.md`
- Modify: `calibration/calibration.json` (add `expect_criteria` for `rms` and `urus`), `docs/calibration-notes.md`, `design-slice4.md` (Amendments)

**Interfaces:**
- Consumes: everything above.
- Produces: the draft in the repo and in `/home/arep/research/drafts/`, golden `expect_criteria` (the bank's `counts` plus `universe` sizes), the recorded hand checks, spec amendments.

- [ ] **Step 1: Write the hardening tests (inputs the earlier tasks do not cover) and run them**

```python
# tests/test_criteria_hardening.py
import time
import unittest

from prd_assistant import criteria, lookup
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_roles import rec


def big_bank(n_routes):
    routes = [{"id": f"r{i}", "method": "GET", "path": f"/api/thing{i}/item", "source": f"a.ts:{i}"} for i in range(n_routes)]
    roles = {"endpoints": {f"r{i}": rec(roles=["ADMIN", "WORKER"] if i % 2 else ["ADMIN"], source=f"a.ts:{i}")
                           for i in range(n_routes)}, "screens": {}, "joined": {}, "mismatches": []}
    rules = {"endpoints": {}, "forms": {}, "mismatches": [], "counts": {}}
    errors = {"messages": [], "sites": {"total": 0, "attached": 0}, "unattached": 0, "not_read": {}, "counts": {"messages": 0}}
    return criteria.build_bank({"routes": routes, "screens": []}, roles, rules, errors)


class ScaleTests(unittest.TestCase):
    def test_a_large_bank_selects_quickly_and_the_cap_holds(self):
        bank = big_bank(6000)
        self.assertGreater(len(bank["candidates"]), 6000)
        started = time.monotonic()
        sel = lookup.select(bank, "thing42 item")
        self.assertLess(time.monotonic() - started, 3)
        self.assertLessEqual(sum(len(s["candidates"]) for s in sel["subjects"]), 60)

    def test_an_empty_repo_builds_an_empty_bank_and_a_normal_one_is_not_truncated(self):
        self.assertFalse(big_bank(50)["truncated"])
        empty = criteria.build_bank(
            {"routes": [], "screens": []}, {"endpoints": {}, "screens": {}, "joined": {}, "mismatches": []},
            {"endpoints": {}, "forms": {}, "mismatches": [], "counts": {}},
            {"messages": [], "sites": {"total": 0, "attached": 0}, "unattached": 0, "not_read": {}, "counts": {"messages": 0}})
        self.assertEqual(empty["candidates"], [])


class HostileTaskTextTests(unittest.TestCase):
    def test_control_characters_ansi_and_enormous_words_are_harmless(self):
        bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
        for text in ("\x1b[31mpayroll\x00", "payroll " + "a" * 1_000_000, "pay‮roll", "💥" * 5000):
            started = time.monotonic()
            sel = lookup.select(bank, text)
            self.assertLess(time.monotonic() - started, 2)
            self.assertLessEqual(len(sel["tokens"]), 600)


class DerivedRefusalHonestyTests(unittest.TestCase):
    def test_refusals_never_name_a_role_that_no_read_endpoint_lists(self):
        bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
        universe = {r.lower() for roles in bank["universe"].values() for r in roles}
        for c in bank["candidates"]:
            if c["kind"] == "role_refused":
                self.assertIn(c["facts"]["role"].lower(), universe)
                self.assertTrue(c["derived"])
                self.assertNotRegex(c["text"], r"\b[1-5]\d\d\b")


if __name__ == "__main__":
    unittest.main()
```

Run: `cd /home/arep/research/prd-assistant && timeout 300 python3 -m unittest tests.test_criteria_hardening 2>&1 | tail -6`
Expected: these exercise behaviour built in Tasks 1 to 5, so they may already pass. **Every one that fails or times out is a real defect:** keep the test, find the cause, fix the code, rerun, then run the whole suite, and record the fix in the ledger.

- [ ] **Step 2: The `team-task` draft and its test (RED first)**

Create `tests/test_team_task_draft.py`:

```python
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "docs" / "team-task-step1-criteria.md"


class TeamTaskDraftTests(unittest.TestCase):
    def test_draft_names_the_real_script_the_exit_codes_and_the_labels(self):
        text = DRAFT.read_text()
        for needle in ("/home/arep/research/prd-assistant/bin/prd_criteria.py lookup", "Exit 2 or 3", "No match",
                       "evidence, not as criteria", "preserve", "change", "derived", "trust note", "`show`"):
            self.assertIn(needle, text)
        self.assertTrue((ROOT / "bin" / "prd_criteria.py").is_file())

    def test_draft_does_not_ask_the_orchestrator_to_edit_or_commit_anything(self):
        text = DRAFT.read_text().lower()
        for forbidden in ("git commit", "git push", "--force"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_team_task_draft 2>&1 | tail -3` (Expected: `FileNotFoundError`), then create `docs/team-task-step1-criteria.md`:

````markdown
# Draft: `team-task` step 1 with acceptance-criteria candidates

Replace step 1 of `~/.claude/commands/team-task.md` with the text below. Nothing here runs by itself; the orchestrator runs the one command in it. The rest of `team-task` is unchanged.

---

1. **Acceptance criteria.** Restate the task as a numbered list of acceptance criteria. If any are missing or ambiguous, ask me and wait for confirmation.
   - **Candidates from the code** (when the repo is a git repo with a CodeGraph index). Before restating, run:
     `python3 -I /home/arep/research/prd-assistant/bin/prd_criteria.py lookup "<repo path>" "<the task text>"`
     - Exit 0: read the output. Its first lines say which commit the facts come from, how old they are and whether the working tree has changed files; carry that into the criteria.
     - Exit 2 or 3: continue without candidates and tell me why (the reason is on stderr).
     - "No match": use the route groups it lists to find the right area, and `show --id <id>` for one candidate in full; do not invent candidates.
   - Treat candidates as **evidence, not as criteria**. For every criterion that rests on a candidate, cite its id (for example `C-ROLE-014`) and label it **preserve** (the behaviour must stay as it is) or **change** (the task alters it; say how).
   - Candidates marked `(derived)` are inferences (a role is refused because the endpoint lists other roles). Label them derived in the criterion and do not state an HTTP status for them.
   - If a criterion rests on a candidate whose trust note says something was not read (for example "router-level dependencies are not followed" or "0 of 15 screens were joined to endpoints"), tell me before step 2 and ask whether to check it by hand.
   - Never write a role, field, limit or message into a criterion unless it is in a candidate or in my task text.
````

Run: `python3 -m unittest tests.test_team_task_draft 2>&1 | tail -3` (Expected: `OK`), then `mkdir -p /home/arep/research/drafts && cp docs/team-task-step1-criteria.md /home/arep/research/drafts/team-task-step1-criteria.md`.

- [ ] **Step 3: Calibrate on the three repos**

```bash
cd /home/arep/research/prd-assistant
S=/home/arep/research/prd-state; rm -rf $S
for spec in "rms|/home/arep/research/targets/room-management-system" "urus|/home/arep/research/targets/Urus" "tis|/home/arep/tis"; do
  IFS='|' read n p <<<"$spec"; echo "== $n"; python3 -I bin/prd_criteria.py build $p --state-dir $S 2>&1 | tail -4; echo "exit=$?"
done
```
Expected: three caches with candidate counts per kind. Exit codes other than 0 are calibration findings to explain in the notes.

Then run `lookup` on realistic task sentences and read the output against the real code:

```bash
python3 -I bin/prd_criteria.py lookup /home/arep/research/targets/room-management-system "let branch admins deactivate a house" --state-dir $S | head -40
python3 -I bin/prd_criteria.py lookup /home/arep/research/targets/room-management-system "tenants can see their own rooms" --state-dir $S | head -30
python3 -I bin/prd_criteria.py lookup /home/arep/research/targets/Urus "let managers approve payroll" --state-dir $S | head -40
python3 -I bin/prd_criteria.py lookup /home/arep/research/targets/Urus "reject receipt scanning for large files" --state-dir $S | head -30
python3 -I bin/prd_criteria.py lookup /home/arep/tis "only admins can delete users" --state-dir $S | head -30
```
Expected (from the code read on 2026-10-14): room-management `POST .../houses/{house}/deactivate` is allowed for `super_admin`, `branch_admin`; Urus `POST .../payroll/{id}/approve` is allowed for the `@FinanceWrite()` roles (`FINANCE`, `ADMIN`) with `MANAGER` shown as refused (derived) and the trust note on the derived candidate; `tis` `DELETE .../users/{user_id}` is allowed for `admin`, `developer`. A task sentence that finds nothing, or finds unrelated subjects, is a **tokenising or matching defect**: write a failing test in `tests/test_lookup.py` (with a trimmed fixture), fix, rerun, and record it as `Task 6: Ruling:` or `Task 6: fixed`.

- [ ] **Step 4: Golden `expect_criteria` and the mutation check**

```bash
cd /home/arep/research/prd-assistant && python3 - <<'EOF'
import json
from pathlib import Path
cal = Path("calibration/calibration.json"); data = json.loads(cal.read_text())
S = Path("/home/arep/research/prd-state")
for key, repo in (("rms", "room-management-system"), ("urus", "Urus")):
    cache = next(p for p in S.iterdir() if p.name.startswith(repo[:40]) and not p.name.startswith(".build-"))
    bank = json.loads((cache / "criteria.json").read_text())
    data["repos"][key]["expect_criteria"] = {"counts": bank["counts"],
                                             "universe": {k: len(v) for k, v in bank["universe"].items()},
                                             "truncated": bank["truncated"]}
cal.write_text(json.dumps(data, indent=2) + "\n")
print({k: ("expect_criteria" in v) for k, v in data["repos"].items()})
EOF
cat > tests/test_calibration_criteria.py <<'EOF'
import json
import tempfile
import unittest
from pathlib import Path

from prd_assistant import criteria, draft, pipeline

CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "calibration.json"


class CriteriaCalibrationTests(unittest.TestCase):
    def test_golden_repos_keep_their_recorded_bank_counts(self):
        spec = json.loads(CALIBRATION.read_text())
        for name, entry in spec["repos"].items():
            if "expect_criteria" not in entry:
                continue
            with self.subTest(repo=name):
                if not Path(entry["path"]).is_dir():
                    self.skipTest(f"{entry['path']} not present")
                with tempfile.TemporaryDirectory() as tmp:
                    facts, result = pipeline.run(entry["path"], use_adapters=entry["use_adapters"])
                    pipeline.write_outputs(tmp, facts, result)
                    draft.dev_prepare(entry["path"], tmp, today="2026-01-01")
                    read = lambda n: json.loads((Path(tmp) / "dev" / n).read_text())
                    bank = criteria.build_bank(facts, read("roles.json"), read("form_rules.json"), read("error_messages.json"))
                got = {"counts": bank["counts"], "universe": {k: len(v) for k, v in bank["universe"].items()},
                       "truncated": bank["truncated"]}
                self.assertEqual(got, entry["expect_criteria"])


if __name__ == "__main__":
    unittest.main()
EOF
echo "--- golden (expect OK):"; python3 -m unittest tests.test_calibration_criteria 2>&1 | tail -2
cp calibration/calibration.json /home/arep/.claude/jobs/022cfe89/tmp/cal4.bak
python3 - <<'EOF'
import json
from pathlib import Path
p = Path("calibration/calibration.json"); d = json.loads(p.read_text())
d["repos"]["urus"]["expect_criteria"]["counts"]["role"] += 1
p.write_text(json.dumps(d, indent=2))
EOF
echo "--- mutation (expect FAIL for urus):"; python3 -m unittest tests.test_calibration_criteria 2>&1 | grep -E "^(FAIL|OK)|FAILED|Ran" | head -3
cp /home/arep/.claude/jobs/022cfe89/tmp/cal4.bak calibration/calibration.json
echo "--- restored (expect OK):"; python3 -m unittest tests.test_calibration_criteria 2>&1 | tail -2
```

- [ ] **Step 5: Notes and spec amendments**

Append `## Slice 4 (criteria candidates for team-task)` to `docs/calibration-notes.md` with: the commands used; a table per repo built by a script from each cache's `meta.json` (routes, screens, candidates per kind, build time, role universe sizes); each task sentence tried with what it selected, whether the expected endpoint was found and any defect fixed; and the known limits (literal matching, ids valid only for the printed commit, derived refusals depend on the universe, typed API clients leave screens unjoined). Append `## Amendments from the slice 4 plan and calibration (<date>)` to `design-slice4.md` listing the five deviations in this plan's header and every calibration decision recorded in the ledger.

- [ ] **Step 6: Whole suite, commit, task-done**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add -A bin prd_assistant tests docs calibration design-slice4.md && git commit -m "feat: team-task step 1 draft, golden criteria calibration, hardening tests, notes and spec amendments

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Then run `task-done` for Task 6 with the whole-suite command.

---

## Final review (after Task 6)

Follow `executing-plans` "Final Review": build the package with `review-package plans/2026-10-14-slice4-criteria-feed.md <MERGE_BASE> HEAD` (MERGE_BASE is the commit the slice 4 branch was cut from, `daf017b`, recorded in the ledger at setup), dispatch one fresh reviewer on the most capable model, read-only and without sub-subagents, with this plan's Review Focus verbatim plus path traversal through the state directory name, reading outside the repo, writes into the repo (including `.git`: confirm the fingerprint takes no optional locks) and performance; re-grade by effect; fix Critical and Important findings in one pass (each RED then GREEN, suite green); ledger minors as `Final: minor (deferred)` and declined-to-judge items as `Final: Ruling:`; delete the plan workspace; end with the lists "Rulings I made" and "Deferred minors" and a `result:` line. The repo is a standalone local project; no interactive branch-finishing step.
