import re
import unittest

from prd_assistant import groups, scaffold

GATE = {"verdict": "WARN", "checks": [
    {"name": "route_agreement", "status": "PASS",
     "detail": {"independent": 3, "extracted": 3, "disagreement": 0.0}},
    {"name": "screen_agreement", "status": "WARN",
     "detail": {"independent": 18, "extracted": 17, "disagreement": 0.0556}},
    {"name": "index_staleness", "status": "PASS", "detail": {"changed_files": 0, "relevant_changed": []}},
    {"name": "orphans", "status": "INFO",
     "detail": {"routes_without_handler": [], "screens_not_navigated_to": ["s2"]}},
]}


def route(rid, method, path, line, tested_by=(), handler="h"):
    return {"id": rid, "kind": "route", "method": method, "path": path, "file": "app/api.py", "line": line,
            "source": f"app/api.py:{line}", "origin": "codegraph", "tested_by": list(tested_by),
            "handler": {"id": "x", "name": handler, "qualified_name": None, "source": f"app/api.py:{line + 1}"}}


def facts():
    return {
        "meta": {"repo": "/r", "codegraph_version": "1.6.2", "extraction_version": "27", "indexed_at_commit": "abc"},
        "routes": [route("R1", "GET", "/api/v1/teams", 3, tested_by=["tests/t.py"]),
                   route("R2", "POST", "/api/v1/teams", 6),
                   route("R3", "GET", "/api/v1/users|x", 9),
                   route("R4", "GET", "/health", 12)],
        "screens": [{"id": "s1", "kind": "screen", "path": "/teams", "file": "web/r.tsx", "line": 5, "source": "web/r.tsx:5"},
                    {"id": "s2", "kind": "screen", "path": "/login", "file": "web/r.tsx", "line": 6, "source": "web/r.tsx:6"}],
        "navigation": [{"id": "n1", "to_id": "s1", "from_symbol": "go", "source": "web/a.tsx:9"}],
        "excluded": [{"id": "e1", "kind": "route", "name": "x", "source": "t:1", "reason": "test"}],
        "adapters": {"laravel": {"routes_added": 0, "unsupported": [{"file": "r.php", "line": 4, "text": "Route::resource("}]}},
    }


def link_data():
    zero = {"call_sites": 0, "matched": 0, "matched_via_prefix": 0, "ambiguous": 0, "unmatched": 0,
            "dynamic": 0, "ignored_candidates": 0}
    return {"schema": 1,
            "tests": {"totals": dict(zero, call_sites=2, matched=1, unmatched=1), "ignored_sample": []},
            "frontend": {"totals": dict(zero), "ignored_sample": []},
            "routes": {"R1": {"http_tests": [{"file": "tests/t.py", "line": 2}], "frontend": []},
                       "R2": {"http_tests": [], "frontend": [{"file": "web/a.ts", "line": 1}]},
                       "R3": {"http_tests": [], "frontend": []}, "R4": {"http_tests": [], "frontend": []}},
            "calls": [{"side": "tests", "file": "tests/t.py", "line": 7, "method": "DELETE",
                       "raw": "/api/v1/nothing", "bucket": "unmatched", "route_ids": []}]}


DOCS = {"schema": 1, "entries": [
    {"id": "D001", "file": "README.md", "heading": "Project", "level": 1, "line": 1, "end_line": 8,
     "excerpt": "Teams help recruiters share searches. Version 2 adds export."}]}


def build(f=None, docs=DOCS, links=None):
    return scaffold.build(f or facts(), GATE, links or link_data(), docs, "myrepo", "2026-10-14")


class ScaffoldTests(unittest.TestCase):
    def test_placeholders_and_template_keys_agree(self):
        text, template = build()
        placeholders = set(re.findall(r"\{\{slot:([^}]+)\}\}", text))
        self.assertEqual(placeholders, {s["key"] for s in template["slots"]})
        self.assertEqual(placeholders, {"problem", "purpose.G01", "purpose.G02", "purpose.G03", "screens_overview"})

    def test_groups_use_the_shared_prefix(self):
        text, _ = build()
        self.assertIn("Feature-group prefix: `/api/v1`", text)
        self.assertIn("### G01 `(root)` (1 routes)", text)
        self.assertIn("### G02 `teams` (2 routes)", text)

    def test_route_table_rows_and_pipe_escaping(self):
        text, _ = build()
        self.assertIn("| GET | `/api/v1/teams` | `app/api.py:3` | h | 1 call(s) in 1 file(s) | 1 file(s) | not detected |", text)
        self.assertIn("| POST | `/api/v1/teams` | `app/api.py:6` | h | none | none | detected |", text)
        self.assertIn("`/api/v1/users\\|x`", text)

    def test_completion_check_counts(self):
        text, _ = build()
        self.assertIn("| G02 `teams` | 2 | 1 | 1 | 1 | 1 | 1 |", text)
        self.assertIn("| G01 `(root)` | 1 | 0 | 0 | 0 | 1 | 0 |", text)
        self.assertIn("| Total | 4 | 1 | 1 | 1 | 3 | 1 |", text)

    def test_stats_function(self):
        g = [x for x in groups.group_routes(facts()["routes"]) if x["key"] == "teams"][0]
        st = scaffold.group_stats(g, link_data()["routes"])
        self.assertEqual((st["routes"], st["http"], st["direct"], st["both"], st["neither"], st["frontend"]),
                         (2, 1, 1, 1, 1, 1))
        self.assertEqual(st["methods"], {"GET": 1, "POST": 1})

    def test_alignment_lists_untested_orphans_exclusions_and_unmatched_calls(self):
        text, _ = build()
        self.assertIn("G01 `(root)`: 1 of 1 routes", text)
        self.assertIn("`/health`", text)
        self.assertIn("/login", text)
        self.assertIn("test: 1", text)
        self.assertIn("Route::resource(", text)
        self.assertIn("DELETE `/api/v1/nothing`", text)
        self.assertIn("NEEDS HUMAN INPUT", text)

    def test_trust_header(self):
        text, _ = build()
        self.assertIn("Gate verdict: **WARN**", text)
        self.assertIn("screen_agreement: WARN (extracted 17, independent 18, disagreement 0.0556)", text)
        self.assertIn("HTTP test calls: 2 (matched 1", text)

    def test_slot_allowed_numbers_and_evidence(self):
        _, template = build()
        slots = {s["key"]: s for s in template["slots"]}
        teams = slots["purpose.G02"]
        self.assertEqual(teams["max_words"], 40)
        self.assertIn("2", teams["allowed_numbers"])      # route count
        self.assertIn("1", teams["allowed_numbers"])      # digits from v1 and the counts
        self.assertIn({"file": "app/api.py", "from_line": 3, "to_line": 3}, teams["allowed_evidence"])
        self.assertIn({"file": "app/api.py", "from_line": 4, "to_line": 4}, teams["allowed_evidence"])  # handler line
        problem = slots["problem"]
        self.assertEqual(problem["allowed_evidence"], [{"file": "README.md", "from_line": 1, "to_line": 8}])
        self.assertIn("2", problem["allowed_numbers"])    # "Version 2" in the excerpt
        self.assertTrue(problem["may_be_needs_human_input"])

    def test_no_docs_prefills_needs_human_input(self):
        text, template = build(docs={"schema": 1, "entries": []})
        self.assertNotIn("{{slot:problem}}", text)
        self.assertNotIn("problem", {s["key"] for s in template["slots"]})
        self.assertIn("## 1. Problem\n\nNEEDS HUMAN INPUT", text)

    def test_repo_with_no_routes_and_no_screens(self):
        f = facts()
        f.update(routes=[], screens=[], navigation=[], excluded=[], adapters={})
        links_data = link_data()
        links_data["routes"] = {}
        links_data["calls"] = []
        text, template = scaffold.build(f, GATE, links_data, {"schema": 1, "entries": []}, "empty", "2026-10-14")
        self.assertIn("No routes were extracted.", text)
        self.assertEqual(template["slots"], [])
        self.assertNotIn("{{slot:", text)

    def test_problem_evidence_cap_and_readme_first(self):
        entries = [{"id": f"D{i:03d}", "file": "docs/a.md" if i else "README.md", "heading": "H", "level": 1,
                    "line": i + 1, "end_line": i + 2, "excerpt": "x" * 1000} for i in range(40)]
        chosen, hidden = scaffold.select_problem_evidence({"entries": entries}, cap=5000)
        self.assertEqual(chosen[0]["file"], "README.md")
        self.assertLessEqual(sum(len(e["heading"]) + len(e["excerpt"]) + 2 for e in chosen), 5000)
        self.assertEqual(len(chosen) + hidden, 40)


if __name__ == "__main__":
    unittest.main()
