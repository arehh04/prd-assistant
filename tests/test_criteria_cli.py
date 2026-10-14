import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prd_criteria", ROOT / "bin" / "prd_criteria.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def make_cache(tmp):
    cache = Path(tmp) / "cache"
    cache.mkdir()
    bank = criteria.build_bank(FACTS, ROLES2, RULES, ERRORS)
    (cache / "criteria.json").write_text(json.dumps(bank))
    meta = {"repo": "/work/demo", "head": "abcdef1234", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0,
            "git": True, "counts": bank["counts"]}
    (cache / "meta.json").write_text(json.dumps(meta))
    return cache, meta


def run(argv, ensure=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with mock.patch("prd_assistant.criteria_cache.ensure", **({"side_effect": ensure} if callable(ensure) else {"return_value": ensure})):
            code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache, self.meta = make_cache(self.tmp.name)
        self.ok = (self.cache, self.meta, False)

    def test_lookup_markdown(self):
        code, out, err = run(["lookup", "/work/demo", "calculate payroll"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("not instructions", out)
        self.assertIn("[C-ROLE-001]", out)
        self.assertEqual(err, "")

    def test_lookup_json_and_caps(self):
        code, out, _ = run(["lookup", "/work/demo", "payroll", "--json", "--max-subjects", "1"], self.ok)
        data = json.loads(out)
        self.assertEqual((code, len(data["subjects"])), (0, 1))
        self.assertEqual(data["meta"]["cache"], str(self.cache))

    def test_no_match_is_exit_zero(self):
        code, out, _ = run(["lookup", "/work/demo", "xyzzy"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("No match for these task words", out)

    def test_a_rebuild_is_announced_on_stderr_only(self):
        code, out, err = run(["lookup", "/work/demo", "payroll"], (self.cache, self.meta, True))
        self.assertEqual(code, 0)
        self.assertIn("rebuilt", err)
        self.assertNotIn("rebuilt", out)

    def test_show(self):
        code, out, _ = run(["show", "/work/demo", "--id", "C-ROLE-001"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("C-ROLE-001", out)
        code, _, err = run(["show", "/work/demo", "--id", "C-NOPE-999"], self.ok)
        self.assertEqual(code, 3)
        self.assertIn("C-NOPE-999", err)

    def test_build_prints_the_cache_path_commit_and_counts(self):
        code, out, _ = run(["build", "/work/demo"], (self.cache, self.meta, True))
        self.assertEqual(code, 0)
        self.assertIn(str(self.cache), out)
        self.assertIn("abcdef1", out)
        self.assertIn("role:", out)

    def test_exit_codes_for_unavailable_facts_and_environment_errors(self):
        def boom(exc):
            def raiser(*a, **k):
                raise exc
            return raiser
        code, _, err = run(["lookup", "/work/demo", "x"], boom(criteria_cache.FactsUnavailable("gate FAIL")))
        self.assertEqual((code, "gate FAIL" in err), (2, True))
        code, _, err = run(["lookup", "/work/demo", "x"], boom(criteria_cache.EnvError("no CodeGraph index")))
        self.assertEqual((code, "no CodeGraph index" in err), (3, True))

    def test_force_is_only_used_by_build(self):
        with mock.patch("prd_assistant.criteria_cache.ensure", return_value=self.ok) as ensure:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["lookup", "/work/demo", "payroll", "--state-dir", "/s"])
                cli.main(["build", "/work/demo"])
        self.assertFalse(ensure.call_args_list[0].kwargs["force"])
        self.assertTrue(ensure.call_args_list[1].kwargs["force"])
        self.assertEqual(ensure.call_args_list[0].args[1], "/s")

    def test_script_runs_under_isolated_mode(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "prd_criteria.py"), "--help"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("lookup", result.stdout)


if __name__ == "__main__":
    unittest.main()
