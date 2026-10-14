import tempfile
import unittest
from pathlib import Path

from prd_assistant import links


def write(root, rel, text, binary=False):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="")


def route(rid, method, path):
    return {"id": rid, "method": method, "path": path}


FACTS = {"routes": [
    route("R1", "GET", "/api/v1/teams"),
    route("R2", "POST", "/api/v1/teams/{id}/members"),
    route("R3", "GET", "/api/v1/users/{id}"),
    route("R4", "POST", "/api/v1/teams"),
    route("R5", "GET", "/api/v1/dup"),
    route("R6", "GET", "/api/v1/dup"),
]}

TEST_PY = '''def test_x(client):
    client.get("/api/v1/teams")
    client.post(f"/api/v1/teams/{tid}/members")
    client.get("/api/v1/users/" + uid)
    client.delete("/api/v1/nothing")
    client.get("/api/v1/dup")
'''

FRONT_TS = """export const a = () => http.post('/teams/1/members')
export const b = () => fetch('/api/v1/teams')
"""


class FrontendRootsTests(unittest.TestCase):
    def test_roots_are_directories_of_router_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/package.json", '{"dependencies": {"react-router-dom": "7"}}')
            write(tmp, "api/package.json", '{"dependencies": {"@nestjs/core": "1"}}')
            write(tmp, "node_modules/x/package.json", '{"dependencies": {"vue-router": "4"}}')
            self.assertEqual(links.frontend_roots(tmp), ["web"])

    def test_root_package_gives_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "package.json", '{"dependencies": {"vue-router": "4"}}')
            self.assertEqual(links.frontend_roots(tmp), [""])


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "tests/test_api.py", TEST_PY)
        write(self.root, "web/package.json", '{"dependencies": {"react-router-dom": "7"}}')
        write(self.root, "web/src/api.ts", FRONT_TS)
        self.result = links.link(self.root, FACTS)

    def test_test_totals_and_identity(self):
        t = self.result["tests"]["totals"]
        self.assertEqual(t, {"call_sites": 5, "matched": 2, "matched_via_prefix": 0, "ambiguous": 1,
                             "unmatched": 1, "dynamic": 1, "ignored_candidates": 0})
        self.assertEqual(t["matched"] + t["ambiguous"] + t["unmatched"] + t["dynamic"], t["call_sites"])

    def test_matched_test_calls_are_credited_to_routes(self):
        r = self.result["routes"]
        self.assertEqual(r["R1"]["http_tests"], [{"file": "tests/test_api.py", "line": 2}])
        self.assertEqual(r["R2"]["http_tests"], [{"file": "tests/test_api.py", "line": 3}])
        self.assertEqual(r["R3"]["http_tests"], [])  # its only caller was dynamic

    def test_ambiguous_and_unmatched_calls_are_never_credited(self):
        r = self.result["routes"]
        self.assertEqual(r["R5"]["http_tests"], [])
        self.assertEqual(r["R6"]["http_tests"], [])
        by_bucket = {c["bucket"]: c for c in self.result["calls"] if c["side"] == "tests"}
        self.assertEqual(sorted(by_bucket["ambiguous"]["route_ids"]), ["R5", "R6"])
        self.assertEqual(by_bucket["unmatched"]["raw"], "/api/v1/nothing")

    def test_frontend_references(self):
        t = self.result["frontend"]["totals"]
        self.assertEqual(t["call_sites"], 2)
        self.assertEqual((t["matched"], t["matched_via_prefix"]), (2, 1))
        r = self.result["routes"]
        self.assertEqual(r["R2"]["frontend"], [{"file": "web/src/api.ts", "line": 1}])
        # fetch with no method: both routes on that path are referenced
        self.assertEqual(r["R1"]["frontend"], [{"file": "web/src/api.ts", "line": 2}])
        self.assertEqual(r["R4"]["frontend"], [{"file": "web/src/api.ts", "line": 2}])
        self.assertEqual(r["R3"]["frontend"], [])

    def test_crlf_bom_and_non_utf8_test_files(self):
        write(self.root, "tests/test_win.py",
              b"\xef\xbb\xbfdef test_w(client):\r\n    # caf\xe9\r\n    client.get('/api/v1/teams')\r\n", binary=True)
        result = links.link(self.root, FACTS)
        files = {(e["file"], e["line"]) for e in result["routes"]["R1"]["http_tests"]}
        self.assertIn(("tests/test_win.py", 3), files)

    def test_repo_without_tests_or_frontend_has_zero_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = links.link(tmp, FACTS)
        self.assertEqual(result["tests"]["totals"]["call_sites"], 0)
        self.assertEqual(result["frontend"]["totals"]["call_sites"], 0)

    def test_no_routes_is_fine(self):
        result = links.link(self.root, {"routes": []})
        self.assertEqual(result["routes"], {})
        t = result["tests"]["totals"]
        self.assertEqual(t["unmatched"], t["call_sites"] - t["dynamic"])


if __name__ == "__main__":
    unittest.main()
