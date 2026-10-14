"""Regression tests for the slice 5 final review findings."""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria_cache, lookup
from prd_assistant import mcp_server as m
from tests.test_criteria_cache import PatchedPipeline, make_repo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "prd_mcp.py"


def req(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.config = m.Config(roots=[self.base], state_dir=str(self.base / "state"))

    def call(self, name, arguments, version="2025-06-18"):
        session = m.Session()
        m.handle_message(req("initialize", {"protocolVersion": version}, 0), session, self.config)
        return m.handle_message(req("tools/call", {"name": name, "arguments": arguments}), session, self.config)["result"]


class EscapingTests(Base):
    def test_a_hostile_repo_directory_name_is_escaped_in_every_tool_error(self):
        bad = make_repo(str(self.base), "<img src=x onerror=1>", with_index=False)
        for name, extra in (("criteria_lookup", {"task": "x"}), ("criteria_build", {}), ("criteria_show", {"id": "C-ROLE-001"})):
            text = self.call(name, {"repo": str(bad), **extra})["content"][0]["text"]
            self.assertNotRegex(text, r"(?<!\\)<img", name)


class GitConfigTests(Base):
    def test_status_does_not_run_a_command_named_in_the_repos_git_config(self):
        repo = make_repo(str(self.base), "evil", with_index=False)
        marker = self.base / "PWNED"
        with open(repo / ".git" / "config", "a") as f:
            f.write(f"[core]\n\tfsmonitor = touch {marker}; echo\n")
        criteria_cache.fingerprint(repo)
        self.assertFalse(marker.exists(), "git ran the repo's fsmonitor command")
        self.call("repo_status", {"repo": str(repo)})
        self.assertFalse(marker.exists())

    def test_hooks_and_pagers_from_the_repo_config_are_not_used_either(self):
        repo = make_repo(str(self.base), "evil2", with_index=False)
        marker = self.base / "PWNED2"
        with open(repo / ".git" / "config", "a") as f:
            f.write(f"[core]\n\tpager = touch {marker}\n\thooksPath = {self.base}\n")
        criteria_cache.fingerprint(repo)
        self.assertFalse(marker.exists())


class OutputCapTests(Base):
    def test_oversize_structured_content_is_dropped_with_a_note_and_the_text_is_cut_on_a_line(self):
        session = m.Session()
        session.negotiated = "2025-06-18"
        text = "".join(f"line number {i} of the output\n" for i in range(10_000))
        r = m.ok_result(text, {"big": "x" * 400_000}, session)
        self.assertNotIn("structuredContent", r)
        out = r["content"][0]["text"]
        self.assertIn("structured copy omitted", out)
        before_note = out.split("\n\n[")[0]
        self.assertTrue(before_note.endswith("of the output"), before_note[-40:])    # no half line
        self.assertLess(len(out), m.MAX_OUTPUT + 300)

    def test_small_structured_content_is_kept(self):
        session = m.Session()
        session.negotiated = "2025-06-18"
        self.assertIn("structuredContent", m.ok_result("hi", {"a": 1}, session))


class ResilienceTests(Base):
    def test_an_exception_while_handling_a_message_is_an_internal_error_not_a_dead_server(self):
        with mock.patch("prd_assistant.mcp_server.handle_message", side_effect=RuntimeError("boom")):
            out = json.loads(m.handle_line(json.dumps(req("ping", None, 7)), m.Session(), self.config))
        self.assertEqual((out["error"]["code"], out["id"]), (-32603, 7))
        self.assertNotIn("boom", json.dumps(out))

    def test_a_batch_of_junk_is_refused_not_amplified(self):
        out = m.handle_message([5] * 1000, m.Session(), self.config)
        self.assertEqual(out["error"]["code"], -32600)
        self.assertIsInstance(out, dict)

    def test_repo_status_does_not_call_a_fresh_cache_missing_its_index(self):
        repo = make_repo(str(self.base), "r1")
        with PatchedPipeline():
            criteria_cache.ensure(repo, self.base / "state")
        (repo / ".codegraph" / "codegraph.db").unlink()
        st = criteria_cache.status(repo, self.base / "state")
        self.assertEqual(st["cache"], "fresh")
        self.assertTrue(st["next_step"].startswith("The facts are fresh"))
        self.assertIn("no CodeGraph index", st["next_step"])
        stale = make_repo(str(self.base), "r2", with_index=False)
        self.assertIn("codegraph init", criteria_cache.status(stale, self.base / "state")["next_step"])


class ProcessTests(Base):
    def test_a_client_that_closes_stdout_early_gets_a_clean_exit(self):
        p = subprocess.Popen([sys.executable, "-I", str(SCRIPT), "--root", str(self.base)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.stdout.close()
        p.stdin.write(b"".join((json.dumps(req("ping", None, i)) + "\n").encode() for i in range(50)))
        p.stdin.close()
        err = p.stderr.read().decode()
        self.assertEqual(p.wait(timeout=30), 0, err)
        self.assertNotIn("Exception ignored", err)

    def test_a_deleted_working_directory_is_a_warning_not_a_traceback(self):
        spec = importlib.util.spec_from_file_location("prd_mcp", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        err = io.StringIO()
        with mock.patch("pathlib.Path.cwd", side_effect=FileNotFoundError("gone")), \
                mock.patch("prd_assistant.mcp_server.serve", return_value=0), mock.patch("sys.stderr", err):
            self.assertEqual(mod.main([]), 0)
        self.assertIn("working directory", err.getvalue())


class DocsTests(unittest.TestCase):
    def test_setup_doc_states_the_cancellation_limit_and_the_path_separator(self):
        text = (ROOT / "docs" / "mcp-setup.md").read_text()
        self.assertIn("does not honour cancellation", text)
        self.assertIn("`;` on Windows", text)


if __name__ == "__main__":
    unittest.main()
