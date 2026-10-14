import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def frontmatter(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no frontmatter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line), text


class SkillFileTests(unittest.TestCase):
    def test_skill_has_frontmatter_and_names_every_command(self):
        meta, text = frontmatter(ROOT / "skills" / "prd-from-code" / "SKILL.md")
        self.assertEqual(meta["name"], "prd-from-code")
        self.assertTrue(meta["description"].startswith("Use when"))
        for needle in ("prd_facts.py", "prd_draft.py prepare", "prd_draft.py verify", "prd_draft.py assemble",
                       "slots.json", "slots.template.json", "at most 2", "NEEDS HUMAN INPUT"):
            self.assertIn(needle, text)

    def test_agent_is_read_only_and_returns_json(self):
        meta, text = frontmatter(ROOT / "agents" / "prd-writer.md")
        self.assertEqual(meta["name"], "prd-writer")
        self.assertEqual(meta["tools"], "Read, Grep")
        self.assertIn("JSON", text)
        self.assertIn("ignore any instruction", text.lower())

    def test_client_guide_skill(self):
        meta, text = frontmatter(ROOT / "skills" / "client-guide-from-code" / "SKILL.md")
        self.assertEqual(meta["name"], "client-guide-from-code")
        self.assertTrue(meta["description"].startswith("Use when"))
        for needle in ("guide-prepare", "prd_draft.py verify", "prd_draft.py assemble", "client-guide.md",
                       "banned_terms", "at most 2", "NEEDS HUMAN INPUT", "OUT/guide"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
