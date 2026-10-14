import json
import shutil
import tempfile
import unittest
from pathlib import Path

from prd_assistant import cgdb, extract
from tests.helpers import make_index, node

ROUTE_ID = "route:backend/api/v1/teams.py:39:POST:"
SCREEN_ID = "route:frontend/src/App.tsx:98:/searches"


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        nodes = [
            node(ROUTE_ID, "route", "POST /api/v1/teams", "backend/api/v1/teams.py", 39),
            node("fn:create_team", "function", "create_team", "backend/api/v1/teams.py", 40),
            node("fn:test_create", "function", "test_create", "tests/test_teams.py", 5),
            node(SCREEN_ID, "route", "/searches", "frontend/src/App.tsx", 98),
            node("fn:go", "function", "handleGo", "frontend/src/pages/Go.tsx", 10),
            node("route:frontend/src/__tests__/mount.ts:3:/login", "route", "/login",
                 "frontend/src/__tests__/mount.ts", 3),
            node("route:gen/api.py:1:GET:", "route", "GET /gen", "gen/api.py", 1),
        ]
        edges = [
            (ROUTE_ID, "fn:create_team", "references", 39, None),
            ("fn:test_create", "fn:create_team", "calls", 9, None),
            ("fn:go", SCREEN_ID, "navigates", 48, json.dumps({"href": "/searches"})),
        ]
        make_index(self.root, nodes=nodes, edges=edges,
                   files=[("gen/api.py", "x", 1)], meta={"indexed_at_commit": "abc123"})
        self.conn, tmp = cgdb.open_index(self.root)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(self.conn.close)
        self.facts = extract.extract_facts(self.conn, self.root)

    def test_backend_route_with_handler_and_test_link(self):
        (route,) = self.facts["routes"]
        self.assertEqual((route["method"], route["path"]), ("POST", "/api/v1/teams"))
        self.assertEqual(route["source"], "backend/api/v1/teams.py:39")
        self.assertEqual((route["file"], route["line"]), ("backend/api/v1/teams.py", 39))
        self.assertEqual(route["handler"]["name"], "create_team")
        self.assertEqual(route["tested_by"], ["tests/test_teams.py"])
        self.assertEqual(route["origin"], "codegraph")

    def test_screen_and_navigation(self):
        (screen,) = self.facts["screens"]
        self.assertEqual(screen["path"], "/searches")
        (nav,) = self.facts["navigation"]
        self.assertEqual((nav["from_symbol"], nav["to_path"], nav["line"]), ("handleGo", "/searches", 48))
        self.assertEqual(nav["source"], "frontend/src/pages/Go.tsx:48")
        self.assertEqual(nav["href"], "/searches")

    def test_test_and_generated_routes_are_excluded_and_listed(self):
        reasons = {e["id"]: e["reason"] for e in self.facts["excluded"]}
        self.assertEqual(reasons["route:frontend/src/__tests__/mount.ts:3:/login"], "test")
        self.assertEqual(reasons["route:gen/api.py:1:GET:"], "generated")

    def test_meta_records_index_provenance(self):
        self.assertEqual(self.facts["schema"], 1)
        self.assertEqual(self.facts["meta"]["indexed_at_commit"], "abc123")
        self.assertEqual(self.facts["meta"]["codegraph_version"], "1.6.2")

    def test_adapter_routes_are_merged_linked_and_not_duplicated(self):
        make_dir = tempfile.TemporaryDirectory()
        self.addCleanup(make_dir.cleanup)
        root2 = Path(make_dir.name)
        make_index(root2, nodes=[
            node("m1", "method", "login", "app/AuthController.php", 12,
                 qn="App\\Http\\Controllers::AuthController::login"),
            node("t1", "method", "testLogin", "tests/AuthTest.php", 3),
        ], edges=[("t1", "m1", "calls", 4, None)])
        conn, tmp = cgdb.open_index(root2)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(conn.close)
        facts = {"routes": [], "adapters": {}}
        routes = [
            {"id": "route:routes/api.php:5:POST:/api/v1/auth/login", "kind": "route", "method": "POST",
             "path": "/api/v1/auth/login", "file": "routes/api.php", "line": 5,
             "source": "routes/api.php:5", "origin": "adapter:laravel",
             "handler_qualified_name": "App\\Http\\Controllers::AuthController::login"},
            {"id": "route:routes/api.php:6:GET:/api/v1/x", "kind": "route", "method": "GET",
             "path": "/api/v1/x", "file": "routes/api.php", "line": 6,
             "source": "routes/api.php:6", "origin": "adapter:laravel",
             "handler_qualified_name": None},
        ]
        extract.merge_adapter_routes(conn, facts, routes, [{"file": "routes/api.php", "line": 9}], "laravel")
        first, second = facts["routes"]
        self.assertEqual(first["handler"]["name"], "login")
        self.assertEqual(first["tested_by"], ["tests/AuthTest.php"])
        self.assertIsNone(second["handler"])
        self.assertEqual(facts["adapters"]["laravel"]["routes_added"], 2)
        self.assertEqual(len(facts["adapters"]["laravel"]["unsupported"]), 1)
        # a second merge of the same (file, line) pairs must add nothing
        extract.merge_adapter_routes(conn, facts, [dict(r) for r in routes], [], "laravel")
        self.assertEqual(len(facts["routes"]), 2)


if __name__ == "__main__":
    unittest.main()
