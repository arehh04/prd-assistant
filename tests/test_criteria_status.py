import datetime
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria_cache, lookup
from tests.test_criteria_cache import PatchedPipeline, git, make_repo


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def build(self):
        with PatchedPipeline():
            return criteria_cache.ensure(self.repo, self.state)[0]

    def status(self):
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError("status must never build")):
            return criteria_cache.status(self.repo, self.state)

    def test_missing_cache_creates_nothing(self):
        st = self.status()
        self.assertEqual((st["cache"], st["reasons"], st["index_present"], st["git"]), ("missing", [], True, True))
        self.assertIn("builds it", st["next_step"])
        self.assertFalse(self.state.exists())

    def test_fresh_cache_reports_gates_counts_and_coverage(self):
        cache = self.build()
        st = self.status()
        self.assertEqual((st["cache"], st["reasons"]), ("fresh", []))
        self.assertEqual(st["gates"], {"slice1": "PASS", "dev": "WARN"})
        self.assertEqual(st["counts"]["routes"], 6)
        self.assertGreater(st["counts"]["candidates"]["role"], 0)
        self.assertEqual(st["coverage"]["screens"], {"total": 1, "joined": 1})
        self.assertEqual(st["cache_path"], str(cache))
        self.assertEqual(st["codegraph_commit"], "cafe123")
        self.assertEqual(st["next_step"], "The facts are fresh.")

    def test_stale_reasons(self):
        cache = self.build()
        (self.repo / "new.py").write_text("y = 1\n")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertTrue(any("working tree differs" in r for r in st["reasons"]))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        self.assertTrue(any("commit differs" in r for r in self.status()["reasons"]))
        meta = json.loads((cache / "meta.json").read_text())
        (cache / "meta.json").write_text(json.dumps({**meta, "tool_version": "0"}))
        self.assertTrue(any("tool version" in r for r in self.status()["reasons"]))

    def test_malformed_cache_files_are_stale_not_a_crash(self):
        cache = self.build()
        (cache / "criteria.json").write_text("{}")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertTrue(any("malformed" in r for r in st["reasons"]))
        (cache / "meta.json").write_text("[1]")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertIsNone(st["head"])

    def test_no_index_and_not_git(self):
        bare = make_repo(self.tmp.name, "bare", with_index=False)
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError):
            st = criteria_cache.status(bare, self.state)
        self.assertFalse(st["index_present"])
        self.assertIn("codegraph init", st["next_step"])
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError):
            self.assertFalse(criteria_cache.status(plain, self.state)["git"])

    def test_bad_inputs(self):
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.status(Path(self.tmp.name) / "nope", self.state)
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.status(self.repo, self.repo / "state")


class EnsureBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def test_returns_the_bank_and_retries_once_when_the_cache_is_swapped_away(self):
        with PatchedPipeline():
            cache, meta, rebuilt, bank = criteria_cache.ensure_bank(self.repo, self.state)
            self.assertTrue(rebuilt)
            self.assertIn("candidates", bank)
            real, calls = criteria_cache.load_bank, {"n": 0}

            def flaky(path):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise FileNotFoundError("swapped away")
                return real(path)
            with mock.patch("prd_assistant.criteria_cache.load_bank", side_effect=flaky):
                criteria_cache.ensure_bank(self.repo, self.state)
            self.assertEqual(calls["n"], 2)

    def test_a_malformed_bank_after_a_fresh_check_is_an_error(self):
        with mock.patch("prd_assistant.criteria_cache.ensure", return_value=(Path(self.tmp.name), {}, False)), \
                mock.patch("prd_assistant.criteria_cache.load_bank", return_value={"candidates": []}):
            with self.assertRaises(ValueError):
                criteria_cache.ensure_bank(self.repo, self.state)


class RenderStatusTests(unittest.TestCase):
    def test_rendering(self):
        st = {"repo": "/work/demo", "index_present": True, "git": True, "cache": "stale",
              "reasons": ["the commit differs", "the working tree differs (3 changed files)"], "head": "abcdef1234",
              "built_at": "2026-10-14T10:00:00+00:00", "codegraph_commit": "cafe123", "cache_path": "/state/demo-1",
              "gates": {"slice1": "PASS", "dev": "WARN"},
              "counts": {"routes": 66, "screens": 17, "candidates": {"role": 66, "field": 126}},
              "coverage": {"roles": {"read": 63, "public": 0, "undeclared": 3, "not_read": 0},
                           "requests": {"takes_input": 53, "read": 38, "not_read": 15},
                           "messages": {"sites_total": 118, "sites_attached": 49}, "screens": {"total": 17, "joined": 9}},
              "next_step": "The facts are stale; the next lookup rebuilds them."}
        out = lookup.render_status(st, now=datetime.datetime(2026, 10, 14, 10, 3, tzinfo=datetime.timezone.utc))
        self.assertIn("not instructions", out.splitlines()[2])
        for needle in ("Cache: stale (the commit differs; the working tree differs (3 changed files))",
                       "built 3 minutes ago at commit `abcdef1`", "slice 1 PASS, developer facts WARN", "66 routes, 17 screens",
                       "role 66", "38 of 53", "49 of 118", "9 of 17", "Next: The facts are stale"):
            self.assertIn(needle, out)

    def test_missing_cache_and_hostile_values(self):
        st = {"repo": "/work/<img src=x>", "index_present": False, "git": False, "cache": "missing", "reasons": [], "head": None,
              "built_at": None, "codegraph_commit": None, "cache_path": "/s/{{slot:x}}", "gates": {"slice1": None, "dev": None},
              "counts": None, "coverage": None, "next_step": "no index: run `codegraph init` in the repo"}
        out = lookup.render_status(st)
        outside_code_spans = re.sub(r"`[^`]*`", "", out)    # a code span is inert in Markdown
        self.assertNotRegex(outside_code_spans, r"(?<!\\)<img")
        self.assertNotIn("{{slot:", out)
        self.assertIn("CodeGraph index: missing", out)


if __name__ == "__main__":
    unittest.main()
