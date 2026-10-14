import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "docs" / "team-task-step1-criteria.md"


class TeamTaskDraftTests(unittest.TestCase):
    def test_draft_names_the_real_script_the_exit_codes_and_the_labels(self):
        text = DRAFT.read_text()
        for needle in ("/home/arep/research/prd-assistant/bin/prd_criteria.py lookup", "Exit 2 or 3", "No match",
                       "evidence, not as criteria", "preserve", "change", "derived", "trust note", "show --id <id>"):
            self.assertIn(needle, text)
        self.assertTrue((ROOT / "bin" / "prd_criteria.py").is_file())

    def test_draft_does_not_ask_the_orchestrator_to_edit_or_commit_anything(self):
        text = DRAFT.read_text().lower()
        for forbidden in ("git commit", "git push", "--force"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
