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
