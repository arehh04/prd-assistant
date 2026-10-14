"""Regression tests for the slice 4 final review findings (important items 1-8 and the cheap minors)."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache, lookup
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_cache import PatchedPipeline, git, make_repo
from tests.test_criteria_roles import ROLES, rec

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prd_criteria", ROOT / "bin" / "prd_criteria.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
META = {"repo": "/work/demo", "head": "abcdef1234567", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0, "git": True,
        "cache": "/state/demo"}


class FingerprintBlindSpotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)

    def rewrite_same_size(self, path, text):
        t0 = 1_700_000_000_000_000_000
        path.write_text(text)
        os.utime(path, ns=(t0, t0))     # a restore from backup or rsync keeps the old mtime

    def test_same_size_rewrite_with_a_preserved_mtime_is_noticed(self):
        f = self.repo / "a.py"
        self.rewrite_same_size(f, "x = 2\n")
        before = criteria_cache.fingerprint(self.repo)
        self.rewrite_same_size(f, "x = 3\n")
        self.assertNotEqual(criteria_cache.fingerprint(self.repo)["dirty"], before["dirty"])

    def test_non_ascii_and_quoted_paths_are_noticed(self):
        for name in ("é.py", "with space.py", 'quo"te.py'):
            f = self.repo / name
            f.write_text("x = 1\n")
            git(self.repo, "add", name)
            git(self.repo, "commit", "-q", "-m", name)
            self.rewrite_same_size(f, "x = 2\n")
            before = criteria_cache.fingerprint(self.repo)
            self.rewrite_same_size(f, "x = 3\n")
            self.assertNotEqual(criteria_cache.fingerprint(self.repo)["dirty"], before["dirty"], name)

    def test_a_repo_argument_that_is_a_subdirectory_sees_its_own_changes(self):
        (self.repo / "sub").mkdir()
        z = self.repo / "sub" / "z.py"
        z.write_text("a = 1\n")
        before = criteria_cache.fingerprint(self.repo / "sub")
        z.write_text("a = 22222\n")
        self.assertNotEqual(criteria_cache.fingerprint(self.repo / "sub")["dirty"], before["dirty"])

    def test_a_commit_inside_a_nested_repository_is_noticed(self):
        nest = self.repo / "nest"
        nest.mkdir()
        git(nest, "init", "-q")
        (nest / "n.py").write_text("n = 1\n")
        git(nest, "add", "n.py")
        git(nest, "commit", "-q", "-m", "one")
        before = criteria_cache.fingerprint(self.repo)
        (nest / "m.py").write_text("m = 1\n")
        git(nest, "add", "m.py")
        git(nest, "commit", "-q", "-m", "two")
        self.assertNotEqual(criteria_cache.fingerprint(self.repo)["dirty"], before["dirty"])

    def test_codegraph_churn_is_still_ignored_from_a_subdirectory_argument(self):
        (self.repo / "sub" / ".codegraph").mkdir(parents=True)
        before = criteria_cache.fingerprint(self.repo / "sub")
        (self.repo / "sub" / ".codegraph" / "x.db").write_text("churn")
        self.assertEqual(criteria_cache.fingerprint(self.repo / "sub")["dirty"], before["dirty"])


class CorruptCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def build_then(self, corrupt):
        with PatchedPipeline() as p:
            cache, _, _ = criteria_cache.ensure(self.repo, self.state)
            corrupt(cache)
            cache2, meta, rebuilt = criteria_cache.ensure(self.repo, self.state)
            self.assertTrue(rebuilt)
            self.assertEqual(p.run.call_count, 2)
            self.assertIn("candidates", criteria_cache.load_bank(cache2))

    def test_meta_that_is_not_an_object_is_rebuilt(self):
        for junk in ("[1]", '"x"', "5", "null", "{not json"):
            with self.subTest(junk=junk):
                shutil_dir = self.state / "x"
                self.build_then(lambda cache, j=junk: (cache / "meta.json").write_text(j))
                shutil_dir  # noqa: B018
                import shutil
                shutil.rmtree(self.state, ignore_errors=True)

    def test_a_bank_that_is_missing_or_malformed_is_rebuilt(self):
        import shutil
        for corrupt in (lambda c: (c / "criteria.json").write_text("{}"), lambda c: (c / "criteria.json").unlink(),
                        lambda c: (c / "criteria.json").write_text("[1, 2]"), lambda c: (c / "criteria.json").write_text("nope")):
            self.build_then(corrupt)
            shutil.rmtree(self.state, ignore_errors=True)

    def test_the_cli_never_prints_a_traceback_for_a_malformed_bank(self):
        cache = Path(self.tmp.name) / "c"
        cache.mkdir()
        (cache / "criteria.json").write_text("{}")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with mock.patch("prd_assistant.criteria_cache.ensure", return_value=(cache, {"repo": "r"}, False)):
                code = cli.main(["lookup", "r", "payroll"])
        self.assertEqual(code, 3)
        self.assertNotIn("Traceback", err.getvalue())

    def test_a_cache_swapped_away_between_the_freshness_check_and_the_read_is_retried_once(self):
        cache = Path(self.tmp.name) / "c"
        cache.mkdir()
        bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
        (cache / "criteria.json").write_text(json.dumps(bank))
        calls = {"n": 0}
        real = criteria_cache.load_bank

        def flaky(path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FileNotFoundError("swapped away")
            return real(path)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with mock.patch("prd_assistant.criteria_cache.ensure", return_value=(cache, {"repo": "r", "git": True}, False)), \
                    mock.patch("prd_assistant.criteria_cache.load_bank", side_effect=flaky):
                code = cli.main(["lookup", "r", "payroll"])
        self.assertEqual(code, 0)
        self.assertIn("Criteria candidates", out.getvalue())


class SwapAndLeftoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def test_a_leftover_old_directory_from_a_crash_does_not_block_the_rebuild(self):
        with PatchedPipeline():
            cache, _, _ = criteria_cache.ensure(self.repo, self.state)
            leftover = cache.with_name(f"{cache.name}.old-{os.getpid()}")
            leftover.mkdir()
            (leftover / "junk").write_text("from a crashed run")
            criteria_cache.ensure(self.repo, self.state, force=True)
        self.assertTrue((cache / "criteria.json").is_file())
        self.assertFalse(leftover.exists())

    def test_old_build_and_old_directories_are_swept_but_recent_ones_are_not(self):
        with PatchedPipeline():
            criteria_cache.ensure(self.repo, self.state)
            old_build, recent_build = self.state / ".build-stale", self.state / ".build-recent"
            old_build.mkdir()
            recent_build.mkdir()
            two_hours_ago = time.time() - 7200
            os.utime(old_build, (two_hours_ago, two_hours_ago))
            criteria_cache.ensure(self.repo, self.state, force=True)
        self.assertFalse(old_build.exists())
        self.assertTrue(recent_build.exists())

    def test_a_state_directory_inside_the_repo_is_refused_and_nothing_is_created(self):
        inside = self.repo / "state"
        with PatchedPipeline():
            with self.assertRaises(criteria_cache.EnvError) as ctx:
                criteria_cache.ensure(self.repo, inside)
        self.assertIn("outside the repo", str(ctx.exception))
        self.assertFalse(inside.exists())


class WordingAndEscapingTests(unittest.TestCase):
    def test_refusal_wording_does_not_claim_more_than_is_known(self):
        cands, _ = criteria.role_candidates({"routes": FACTS["routes"][:2], "screens": []},
                                            {"endpoints": {"r1": ROLES["endpoints"]["r1"], "r2": ROLES["endpoints"]["r2"]},
                                             "screens": {}, "joined": {}, "mismatches": []})
        text = next(c["text"] for c in cands if c["kind"] == "role_refused")
        self.assertEqual(text, "Role WORKER is not in the role list of POST /api/payroll/calculate, so it is treated as refused.")

    def test_show_escapes_hostile_facts(self):
        hostile = "<img src=x onerror=1> **bold** [x](http://e.example) {{slot:a}} ‮"
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": hostile,
                                          "via": "handler", "source": "api/c.ts:7"}]}
        bank = criteria.build_bank(FACTS, ROLES2, RULES, errors)
        c = next(c for c in bank["candidates"] if c["kind"] == "error")
        out = lookup.render_candidate(c, META)
        self.assertNotRegex(out, r"(?<!\\)<img")
        self.assertNotIn("](http://e.example)", out.replace("\\]", "").replace("\\[", ""))
        self.assertNotIn("{{slot:", out)
        self.assertNotIn("‮", out)

    def test_invisible_direction_controls_are_stripped_from_the_rendered_markdown(self):
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": "pay‮roll​x⁦y",
                                          "via": "handler", "source": "api/c.ts:7"}]}
        bank = criteria.build_bank(FACTS, ROLES2, RULES, errors)
        out = lookup.render_markdown(lookup.select(bank, "payroll calculate"), META, bank)
        for ch in ("‮", "⁦", "​"):
            self.assertNotIn(ch, out)

    def test_json_output_is_ascii_only(self):
        cache = tempfile_cache()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with mock.patch("prd_assistant.criteria_cache.ensure", return_value=(cache, {"repo": "r", "git": True}, False)):
                cli.main(["lookup", "r", "payroll", "--json"])
        out.getvalue().encode("ascii")    # raises if a raw non-ASCII character got through

    def test_no_commits_is_not_called_not_a_git_repository(self):
        bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
        out = lookup.render_markdown(lookup.select(bank, "payroll"), {**META, "git": False, "changed": None}, bank)
        self.assertIn("not a git repository or it has no commits", out)


def tempfile_cache():
    d = Path(tempfile.mkdtemp())
    errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": "café ‮",
                                      "via": "handler", "source": "api/c.ts:7"}]}
    (d / "criteria.json").write_text(json.dumps(criteria.build_bank(FACTS, ROLES2, RULES, errors)))
    return d


if __name__ == "__main__":
    unittest.main()
