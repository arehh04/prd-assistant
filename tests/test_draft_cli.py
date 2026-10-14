import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prd_assistant import assemble, pipeline
from tests.test_pipeline import build_repo

CLI = Path(__file__).resolve().parent.parent / "bin" / "prd_draft.py"


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True)


def slice1(tmp, index_lines=(3, 6)):
    repo, out = Path(tmp) / "repo", Path(tmp) / "out"
    repo.mkdir()
    build_repo(repo, index_lines=index_lines)
    facts, result = pipeline.run(repo)
    pipeline.write_outputs(out, facts, result)
    return repo, out


def good_slots(out):
    template = json.loads((out / "slots.template.json").read_text())
    slots = {}
    for s in template["slots"]:
        ev = s["allowed_evidence"][0]
        slots[s["key"]] = f"Handles one endpoint. [{ev['file']}:{ev['from_line']}]"
    return slots


class AssembleTests(unittest.TestCase):
    TEMPLATE = {"slots": [{"key": "a", "max_words": 10, "may_be_needs_human_input": True,
                           "allowed_evidence": [{"file": "f.py", "from_line": 1, "to_line": 1}],
                           "evidence_text": [{"file": "f.py", "from_line": 1, "to_line": 1, "text": "x"}],
                           "allowed_numbers": []}]}

    def test_substitution_is_single_pass_and_adds_footer(self):
        text = assemble.assemble("# T\n\n{{slot:a}}\n", {"a": "Fine. [f.py:1]"}, self.TEMPLATE)
        self.assertIn("Fine. [f.py:1]", text)
        self.assertNotIn("{{slot:", text)
        self.assertIn("NOT verified", text)

    def test_lint_failure_refuses(self):
        with self.assertRaises(assemble.AssembleError):
            assemble.assemble("{{slot:a}}", {"a": "no citation"}, self.TEMPLATE)

    def test_scaffold_and_template_disagreement_refuses(self):
        with self.assertRaises(assemble.AssembleError):
            assemble.assemble("{{slot:a}} {{slot:b}}", {"a": "Fine. [f.py:1]"}, self.TEMPLATE)


class CliTests(unittest.TestCase):
    def test_prepare_verify_assemble_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = slice1(tmp)
            done = run_cli("prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            for name in ("docs_index.json", "links.json", "scaffold.md", "slots.template.json", "draft_summary.json"):
                self.assertTrue((out / name).is_file(), name)
            template = json.loads((out / "slots.template.json").read_text())
            self.assertEqual([s["key"] for s in template["slots"]], ["purpose.G01", "purpose.G02"])
            (out / "slots.json").write_text(json.dumps(good_slots(out)))
            self.assertEqual(run_cli("verify", "--out", str(out)).returncode, 0)
            done = run_cli("assemble", "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            prd = (out / "prd.md").read_text()
            self.assertIn("Handles one endpoint.", prd)
            self.assertIn("## 1. Problem\n\nNEEDS HUMAN INPUT", prd)  # the repo has no docs
            self.assertNotIn("{{slot:", prd)

    def test_verify_reports_a_fabricated_number_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = slice1(tmp)
            run_cli("prepare", str(repo), "--out", str(out))
            slots = good_slots(out)
            slots["purpose.G01"] = "Serves 47 endpoints. [app/api.py:3]"
            (out / "slots.json").write_text(json.dumps(slots))
            done = run_cli("verify", "--out", str(out))
            self.assertEqual(done.returncode, 1)
            self.assertEqual(json.loads(done.stdout)[0]["rule"], "numbers")
            self.assertEqual(run_cli("assemble", "--out", str(out)).returncode, 1)
            self.assertFalse((out / "prd.md").exists())

    def test_gate_fail_stops_prepare_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = slice1(tmp, index_lines=(3,))  # index misses a route, so the gate FAILs
            done = run_cli("prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("gate", done.stderr.lower())
            for name in ("scaffold.md", "links.json", "slots.template.json", "docs_index.json"):
                self.assertFalse((out / name).exists(), name)

    def test_prepare_without_slice1_outputs_exits_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            done = run_cli("prepare", str(repo), "--out", str(Path(tmp) / "empty-out"))
            self.assertEqual(done.returncode, 3)
            self.assertIn("prd_facts.py", done.stderr)

    def test_verify_without_slots_exits_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = slice1(tmp)
            run_cli("prepare", str(repo), "--out", str(out))
            done = run_cli("verify", "--out", str(out))
            self.assertEqual(done.returncode, 3)
            self.assertIn("slots.json", done.stderr)


if __name__ == "__main__":
    unittest.main()
