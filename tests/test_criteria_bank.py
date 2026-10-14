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
