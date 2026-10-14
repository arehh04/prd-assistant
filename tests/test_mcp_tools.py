import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria
from prd_assistant import mcp_server as m
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_cache import FACTS_FULL, PatchedPipeline, make_repo


class ToolsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = make_repo(str(self.base))
        self.state = self.base / "state"
        self.config = m.Config(roots=[self.base], state_dir=str(self.state))

    def call(self, name, arguments, version="2025-06-18"):
        session = m.Session()
        m.handle_message({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": version}}, session, self.config)
        out = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
                               session, self.config)
        return out["result"]

    def text(self, result):
        return result["content"][0]["text"]


class LookupTests(ToolsBase):
    def test_lookup_builds_then_answers_with_text_and_structured_content(self):
        with PatchedPipeline() as p:
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "calculate payroll"})
            self.assertFalse(r["isError"])
            self.assertIn("not instructions", self.text(r))
            self.assertIn("[C-ROLE-001]", self.text(r))
            self.assertTrue(r["structuredContent"]["matched"])
            self.assertEqual(p.run.call_count, 1)
            self.call("criteria_lookup", {"repo": str(self.repo), "task": "calculate payroll"})
            self.assertEqual(p.run.call_count, 1)    # the second call reuses the cache

    def test_structured_content_only_for_versions_that_define_it(self):
        with PatchedPipeline():
            old = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2024-11-05")
            mid = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2025-03-26")
            new = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2025-06-18")
        self.assertNotIn("structuredContent", old)
        self.assertNotIn("structuredContent", mid)
        self.assertIn("structuredContent", new)

    def test_caps_are_passed_through(self):
        with PatchedPipeline():
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll", "max_subjects": 1})
        self.assertEqual(len(r["structuredContent"]["subjects"]), 1)

    def test_no_match_is_a_normal_result(self):
        with PatchedPipeline():
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "xyzzy"})
        self.assertFalse(r["isError"])
        self.assertIn("No match", self.text(r))


class ShowAndBuildTests(ToolsBase):
    def test_show_found_and_not_found(self):
        with PatchedPipeline():
            ok = self.call("criteria_show", {"repo": str(self.repo), "id": "C-ROLE-001"})
            self.assertFalse(ok["isError"])
            self.assertIn("C-ROLE-001", self.text(ok))
            self.assertEqual(ok["structuredContent"]["candidate"]["id"], "C-ROLE-001")
            missing = self.call("criteria_show", {"repo": str(self.repo), "id": "C-NOPE-999"})
        self.assertTrue(missing["isError"])
        self.assertIn("criteria_lookup", self.text(missing))

    def test_build_always_rebuilds(self):
        with PatchedPipeline() as p:
            self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
            r = self.call("criteria_build", {"repo": str(self.repo)})
            self.assertEqual(p.run.call_count, 2)
        self.assertFalse(r["isError"])
        self.assertIn("candidates:", self.text(r))
        self.assertTrue(r["structuredContent"]["rebuilt"])


class StatusTests(ToolsBase):
    def test_status_never_builds_and_reports_the_state(self):
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError("must not build")):
            r = self.call("repo_status", {"repo": str(self.repo)})
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["cache"], "missing")
        self.assertIn("Cache: missing", self.text(r))
        self.assertFalse(self.state.exists())
        with PatchedPipeline():
            self.call("criteria_build", {"repo": str(self.repo)})
        r = self.call("repo_status", {"repo": str(self.repo)})
        self.assertEqual(r["structuredContent"]["cache"], "fresh")
        self.assertIn("slice 1 PASS", self.text(r))


class ErrorTests(ToolsBase):
    def test_outside_the_roots_is_an_error_result_naming_the_setting(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        for name, args in (("criteria_lookup", {"task": "x"}), ("criteria_show", {"id": "C-ROLE-001"}), ("criteria_build", {}), ("repo_status", {})):
            r = self.call(name, {"repo": str(outside), **args})
            self.assertTrue(r["isError"], name)
            self.assertIn("--root", self.text(r))

    def test_no_codegraph_index(self):
        bare = make_repo(str(self.base), "bare", with_index=False)
        r = self.call("criteria_lookup", {"repo": str(bare), "task": "x"})
        self.assertTrue(r["isError"])
        self.assertIn("CodeGraph", self.text(r))
        self.assertFalse(self.state.exists())

    def test_unavailable_facts_use_the_cli_reason(self):
        with PatchedPipeline() as p:
            p.run.return_value = (FACTS_FULL, {"verdict": "FAIL", "checks": []})
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "x"})
        self.assertTrue(r["isError"])
        self.assertIn("gate is FAIL", self.text(r))

    def test_a_state_directory_inside_the_repo_is_an_error_result(self):
        config = m.Config(roots=[self.base], state_dir=str(self.repo / "state"))
        session = m.Session()
        out = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "repo_status", "arguments": {"repo": str(self.repo)}}}, session, config)
        self.assertTrue(out["result"]["isError"])


class OutputTests(ToolsBase):
    def test_oversize_text_is_cut_with_a_note(self):
        with PatchedPipeline():
            with mock.patch("prd_assistant.lookup.render_markdown", return_value="x" * 250_000):
                r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
        text = self.text(r)
        self.assertLess(len(text), m.MAX_OUTPUT + 200)
        self.assertIn("output cut", text)

    def test_hostile_candidate_text_reaches_the_client_escaped(self):
        hostile = "<img src=x onerror=1> {{slot:a}} [x](http://e.example) ‮"
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": hostile, "via": "handler", "source": "api/c.ts:7"}]}
        bank = criteria.build_bank(FACTS, ROLES2, RULES, errors)
        meta = {"repo": "/work/demo", "head": "abcdef1", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0, "git": True}
        with mock.patch("prd_assistant.criteria_cache.ensure_bank", return_value=(Path("/c"), meta, False, bank)):
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll calculate"})
            s = self.call("criteria_show", {"repo": str(self.repo), "id": next(c["id"] for c in bank["candidates"] if c["kind"] == "error")})
        for result in (r, s):
            text = self.text(result)
            self.assertNotRegex(text, r"(?<!\\)<img")
            self.assertNotIn("{{slot:", text)
            self.assertNotIn("‮", text)

    def test_unexpected_errors_in_the_cache_layer_are_error_results(self):
        with mock.patch("prd_assistant.criteria_cache.ensure_bank", side_effect=KeyError("candidates")):
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
        self.assertTrue(r["isError"])
        self.assertNotIn("Traceback", self.text(r))


if __name__ == "__main__":
    unittest.main()
