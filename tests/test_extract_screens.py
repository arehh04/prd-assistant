import json
import shutil
import tempfile
import unittest
from pathlib import Path

from prd_assistant import cgdb, extract
from tests.helpers import make_index, node

REAL_ID = "route:web/router.ts:5:/login"
TEST_ID = "route:web/__tests__/mount.ts:3:/login"
AMBIG_A = "route:web/router.ts:9:/dup"
AMBIG_B = "route:web/router.ts:12:/dup"
TEST_DUP = "route:web/__tests__/mount.ts:6:/dup"


def facts_for(nodes, edges):
    root = Path(tempfile.mkdtemp())
    make_index(root, nodes=nodes, edges=edges)
    conn, tmp = cgdb.open_index(root)
    try:
        return extract.extract_facts(conn, root)
    finally:
        conn.close()
        shutil.rmtree(tmp)
        shutil.rmtree(root)


class ScreenFactsTests(unittest.TestCase):
    def test_screen_carries_the_component_link(self):
        nodes = [node(REAL_ID, "route", "/login", "web/router.ts", 5),
                 node("c:login", "function", "LoginPage", "web/pages/LoginPage.tsx", 7),
                 node("route:web/router.ts:6:/plain", "route", "/plain", "web/router.ts", 6)]
        facts = facts_for(nodes, [(REAL_ID, "c:login", "references", 5, None)])
        by_path = {s["path"]: s for s in facts["screens"]}
        self.assertEqual(by_path["/login"]["component"],
                         {"name": "LoginPage", "file": "web/pages/LoginPage.tsx", "line": 7})
        self.assertIsNone(by_path["/plain"]["component"])

    def test_navigation_to_a_test_route_is_reattached_to_the_real_screen(self):
        nodes = [node(REAL_ID, "route", "/login", "web/router.ts", 5),
                 node(TEST_ID, "route", "/login", "web/__tests__/mount.ts", 3),
                 node("fn:go", "function", "go", "web/Go.vue", 10)]
        facts = facts_for(nodes, [("fn:go", TEST_ID, "navigates", 12, json.dumps({"href": "/login"}))])
        (nav,) = facts["navigation"]
        self.assertEqual((nav["to_id"], nav["reattached"]), (REAL_ID, True))
        self.assertFalse([e for e in facts["excluded"] if e["kind"] == "navigation"])

    def test_ordinary_navigation_is_not_marked_reattached(self):
        nodes = [node(REAL_ID, "route", "/login", "web/router.ts", 5), node("fn:go", "function", "go", "web/Go.vue", 10)]
        facts = facts_for(nodes, [("fn:go", REAL_ID, "navigates", 12, None)])
        self.assertFalse(facts["navigation"][0]["reattached"])

    def test_ambiguous_or_missing_real_screen_stays_excluded(self):
        nodes = [node(AMBIG_A, "route", "/dup", "web/router.ts", 9), node(AMBIG_B, "route", "/dup", "web/router.ts", 12),
                 node(TEST_DUP, "route", "/dup", "web/__tests__/mount.ts", 6),
                 node("route:web/__tests__/mount.ts:8:/only-in-tests", "route", "/only-in-tests", "web/__tests__/mount.ts", 8),
                 node("fn:go", "function", "go", "web/Go.vue", 10)]
        edges = [("fn:go", TEST_DUP, "navigates", 20, None),
                 ("fn:go", "route:web/__tests__/mount.ts:8:/only-in-tests", "navigates", 21, None)]
        facts = facts_for(nodes, edges)
        self.assertEqual(facts["navigation"], [])
        reasons = [e["reason"] for e in facts["excluded"] if e["kind"] == "navigation"]
        self.assertEqual(reasons, ["target-excluded", "target-excluded"])


if __name__ == "__main__":
    unittest.main()
