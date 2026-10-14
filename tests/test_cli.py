import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_index
from tests.test_pipeline import build_repo

CLI = Path(__file__).resolve().parent.parent / "bin" / "prd_facts.py"


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True)


class CliTests(unittest.TestCase):
    def test_pass_exits_zero_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = Path(tmp) / "repo", Path(tmp) / "out"
            repo.mkdir()
            build_repo(repo)
            done = run_cli(str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("PASS", done.stdout)
            self.assertEqual(json.loads((out / "summary.json").read_text())["routes_extracted"], 2)

    def test_fail_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = Path(tmp) / "repo", Path(tmp) / "out"
            repo.mkdir()
            build_repo(repo, index_lines=(3,))
            done = run_cli(str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 2)
            self.assertIn("FAIL", done.stdout)

    def test_unsupported_codegraph_version_exits_three_with_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_index(repo, schema_version=10)
            done = run_cli(str(repo), "--out", str(Path(tmp) / "out"))
            self.assertEqual(done.returncode, 3)
            self.assertIn("schema=10", done.stderr)

    def test_missing_repo_exits_three(self):
        done = run_cli("/no/such/repo/anywhere")
        self.assertEqual(done.returncode, 3)
        self.assertIn("not a directory", done.stderr)


if __name__ == "__main__":
    unittest.main()
