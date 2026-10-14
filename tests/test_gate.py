import shutil
import tempfile
import unittest
from pathlib import Path

from prd_assistant import cgdb, gate, report
from tests.helpers import make_index, sha256_file

CFG = gate.load_config()


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class PureFunctionTests(unittest.TestCase):
    def test_compare_reports_both_directions(self):
        d = gate.compare({("a", 1), ("b", 2)}, {("a", 1), ("c", 3), ("d", 4)})
        self.assertEqual(d["missing_in_codegraph"], [("c", 3), ("d", 4)])
        self.assertEqual(d["extra_in_codegraph"], [("b", 2)])
        self.assertEqual(d["disagreement"], 1.0)  # 3 differences over 3 independent
        self.assertEqual((d["independent"], d["extracted"]), (3, 2))

    def test_compare_handles_empty_sides(self):
        self.assertEqual(gate.compare(set(), set())["disagreement"], 0.0)
        self.assertEqual(gate.compare({("a", 1)}, set())["disagreement"], 1.0)

    def test_grade_thresholds(self):
        t = {"pass": 0.05, "warn": 0.20}
        self.assertEqual(gate.grade(0.0, t), "PASS")
        self.assertEqual(gate.grade(0.05, t), "PASS")
        self.assertEqual(gate.grade(0.2, t), "WARN")
        self.assertEqual(gate.grade(0.21, t), "FAIL")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _conn(self):
        conn, tmp = cgdb.open_index(self.root)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(conn.close)
        return conn

    def _repo_with_two_fastapi_routes(self, indexed_route_lines=(3, 6)):
        src = "router = APIRouter()\n\n@router.get('/a')\ndef a(): ...\n\n@router.post('/b')\ndef b(): ...\n"
        path = write(self.root, "app/api.py", src)
        make_index(self.root, files=[("app/api.py", sha256_file(path), 0)])
        facts = {"routes": [{"id": f"r{n}", "file": "app/api.py", "line": n, "handler": {"id": "h"}}
                            for n in indexed_route_lines],
                 "screens": [], "navigation": [], "excluded": [], "adapters": {}}
        return facts

    def _check(self, result, name):
        return next(c for c in result["checks"] if c["name"] == name)

    def test_matching_repo_passes(self):
        facts = self._repo_with_two_fastapi_routes()
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(self._check(result, "route_agreement")["status"], "PASS")
        self.assertEqual(gate.summary(result)["routes_independent"], 2)

    def test_missing_route_fails_and_names_it(self):
        facts = self._repo_with_two_fastapi_routes(indexed_route_lines=(3,))
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        check = self._check(result, "route_agreement")
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["detail"]["missing_in_codegraph"], [("app/api.py", 6)])
        self.assertEqual(result["verdict"], "FAIL")

    def test_no_framework_detected_is_a_warning_not_a_pass(self):
        write(self.root, "lib/util.py", "x = 1\n")
        make_index(self.root, files=[("lib/util.py", sha256_file(self.root / "lib/util.py"), 0)])
        facts = {"routes": [], "screens": [], "navigation": [], "excluded": [], "adapters": {}}
        result = gate.run(self._conn(), self.root, facts, set(), CFG, head=None)
        self.assertEqual(self._check(result, "route_agreement")["status"], "WARN")
        self.assertEqual(result["verdict"], "WARN")

    def test_route_file_edited_after_indexing_fails_staleness(self):
        facts = self._repo_with_two_fastapi_routes()
        (self.root / "app/api.py").write_text("router = APIRouter()\n\n@router.get('/a')\ndef a(): ...\n\n"
                                              "@router.post('/b')\ndef b(): ...\n# edited\n")
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        check = self._check(result, "index_staleness")
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["detail"]["relevant_changed"], ["app/api.py"])

    def test_unrelated_file_change_is_only_a_warning(self):
        facts = self._repo_with_two_fastapi_routes()
        helper = write(self.root, "lib/util.py", "x = 1\n")
        # index lib/util.py too, then change it
        conn = self._conn()
        conn.execute("insert into files (path, content_hash, generated) values (?, ?, 0)",
                     ("lib/util.py", sha256_file(helper)))
        helper.write_text("x = 2\n")
        result = gate.run(conn, self.root, facts, {"fastapi"}, CFG, head=None)
        self.assertEqual(self._check(result, "index_staleness")["status"], "WARN")

    def test_low_language_coverage_fails(self):
        facts = self._repo_with_two_fastapi_routes()
        for i in range(5):  # five more source files on disk that the index does not know
            write(self.root, f"extra/m{i}.py", "pass\n")
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        check = self._check(result, "language_coverage")
        self.assertEqual(check["status"], "FAIL")
        self.assertAlmostEqual(check["detail"]["ratio"], 1 / 6, places=3)

    def test_adapter_unsupported_constructs_warn(self):
        facts = self._repo_with_two_fastapi_routes()
        facts["adapters"] = {"laravel": {"routes_added": 0, "unsupported": [{"file": "r.php", "line": 3, "text": "x"}]}}
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        self.assertEqual(self._check(result, "adapter_unsupported")["status"], "WARN")

    def test_orphans_and_exclusions_are_informational_and_listed(self):
        facts = self._repo_with_two_fastapi_routes()
        facts["routes"][0]["handler"] = None
        facts["excluded"] = [{"id": "e1", "kind": "route", "name": "x", "source": "t.py:1", "reason": "test"}]
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        self.assertEqual(self._check(result, "orphans")["status"], "INFO")
        self.assertEqual(self._check(result, "orphans")["detail"]["routes_without_handler"], ["r3"])
        self.assertEqual(self._check(result, "exclusions")["detail"]["by_reason"], {"test": 1})
        self.assertEqual(result["verdict"], "PASS")

    def test_report_mentions_verdict_and_differences(self):
        facts = self._repo_with_two_fastapi_routes(indexed_route_lines=(3,))
        facts["meta"] = {"repo": str(self.root), "codegraph_version": "1.6.2",
                         "extraction_version": "27", "indexed_at_commit": None}
        result = gate.run(self._conn(), self.root, facts, {"fastapi"}, CFG, head=None)
        md = report.render_gate_md(result, facts)
        self.assertIn("FAIL", md)
        self.assertIn("app/api.py:6", md)


if __name__ == "__main__":
    unittest.main()
