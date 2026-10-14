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
        self.assertEqual(c["text"], "Role WORKER is not in the role list of POST /api/payroll/calculate, so it is treated as refused.")
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
