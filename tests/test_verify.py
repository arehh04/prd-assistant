import unittest

from prd_assistant import verify

SLOT = {
    "key": "purpose.G01", "max_words": 12, "may_be_needs_human_input": True,
    "allowed_evidence": [{"file": "app/api.py", "from_line": 3, "to_line": 3},
                         {"file": "README.md", "from_line": 1, "to_line": 10}],
    "evidence_text": [
        {"file": "app/api.py", "from_line": 3, "to_line": 3, "text": "GET /teams handler list_teams"},
        {"file": "README.md", "from_line": 1, "to_line": 10, "text": "Teams help recruiters share searches."}],
    "allowed_numbers": ["34", "1"],
}
TEMPLATE = {"slots": [SLOT]}


def check(text, template=TEMPLATE, key="purpose.G01"):
    return verify.verify({key: text}, template)


def rules(errors):
    return sorted({e["rule"] for e in errors})


class VerifyTests(unittest.TestCase):
    def test_a_good_slot_passes(self):
        self.assertEqual(check("Lists teams for recruiters. [app/api.py:3]"), [])

    def test_needs_human_input_is_allowed_where_permitted(self):
        self.assertEqual(check("NEEDS HUMAN INPUT"), [])

    def test_needs_human_input_rejected_where_not_permitted(self):
        strict = {"slots": [dict(SLOT, may_be_needs_human_input=False)]}
        self.assertEqual(rules(check("NEEDS HUMAN INPUT", strict)), ["citation"])

    def test_missing_citation(self):
        self.assertEqual(rules(check("Lists teams for recruiters.")), ["citation"])

    def test_dead_citation_file(self):
        self.assertEqual(rules(check("Lists teams. [other/file.py:3]")), ["resolves"])

    def test_citation_line_outside_range(self):
        self.assertEqual(rules(check("Lists teams. [app/api.py:4]")), ["resolves"])

    def test_fabricated_number(self):
        errors = check("Serves 47 teams. [app/api.py:3]")
        self.assertEqual(rules(errors), ["numbers"])
        self.assertIn("47", errors[0]["detail"])

    def test_allowed_number_and_citation_digits_are_ignored(self):
        self.assertEqual(check("Serves 34 teams. [app/api.py:3]"), [])

    def test_missing_and_unknown_keys(self):
        errors = verify.verify({"purpose.G99": "x"}, TEMPLATE)
        self.assertEqual(rules(errors), ["keys"])
        self.assertEqual(len(errors), 2)

    def test_markdown_structure_is_rejected(self):
        for text in ("| a | b |\n|---|---|\n[app/api.py:3]", "# Title [app/api.py:3]", "- item [app/api.py:3]",
                     "Text\n\nSecond paragraph [app/api.py:3]", "```\ncode\n``` [app/api.py:3]"):
            self.assertEqual(rules(check(text)), ["form"], text)

    def test_template_injection_is_rejected(self):
        self.assertIn("form", rules(check("See {{slot:problem}} [app/api.py:3]")))

    def test_too_long(self):
        self.assertIn("length", rules(check(" ".join(["word"] * 13) + " [app/api.py:3]")))

    def test_verbatim_quote_from_cited_file_passes(self):
        self.assertEqual(check('The docs say "Teams help recruiters" [README.md:2]'), [])

    def test_fabricated_quote_fails(self):
        self.assertEqual(rules(check('The docs say "Teams ship fast" [README.md:2]')), ["quotes"])

    def test_quote_from_an_uncited_file_fails(self):
        self.assertEqual(rules(check('It says "Teams help recruiters" [app/api.py:3]')), ["quotes"])

    def test_non_string_value(self):
        self.assertEqual(rules(verify.verify({"purpose.G01": 5}, TEMPLATE)), ["form"])

    def test_non_object_input(self):
        self.assertEqual(rules(verify.verify(["x"], TEMPLATE)), ["keys"])


if __name__ == "__main__":
    unittest.main()
