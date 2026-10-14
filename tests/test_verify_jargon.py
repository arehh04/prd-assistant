import unittest

from prd_assistant import verify

BANNED = ["api", "apis", "endpoint", "route", "status code", "token"]
SLOT = {
    "key": "screen.S01", "max_words": 40, "may_be_needs_human_input": True, "banned_terms": BANNED,
    "allowed_evidence": [{"file": "web/Login.tsx", "from_line": 1, "to_line": 20}],
    "evidence_text": [{"file": "web/Login.tsx", "from_line": 3, "to_line": 3, "text": "button: Reset API token"}],
    "allowed_numbers": [],
}


def check(text, slot=SLOT):
    return verify.verify({slot["key"]: text}, {"slots": [slot]})


def rules(errors):
    return sorted({e["rule"] for e in errors})


class JargonTests(unittest.TestCase):
    def test_plain_language_passes(self):
        self.assertEqual(check("Sign in with your email and password. [web/Login.tsx:3]"), [])

    def test_banned_words_are_rejected_case_insensitively(self):
        for text in ("Calls the API to sign in. [web/Login.tsx:3]", "The endpoint checks you. [web/Login.tsx:3]",
                     "Shows the HTTP status code. [web/Login.tsx:3]", "Uses an Api key. [web/Login.tsx:3]"):
            self.assertEqual(rules(check(text)), ["jargon"], text)

    def test_look_alike_words_do_not_trip_the_rule(self):
        self.assertEqual(check("Open the application and the rapid view. [web/Login.tsx:3]"), [])

    def test_quoted_labels_and_citations_are_exempt(self):
        self.assertEqual(check('Choose "Reset API token" to start over. [web/Login.tsx:3]'), [])

    def test_the_error_names_the_offending_terms(self):
        (error,) = check("The route and the token matter. [web/Login.tsx:3]")
        self.assertIn("route", error["detail"])
        self.assertIn("token", error["detail"])

    def test_slots_without_banned_terms_are_unaffected(self):
        plain = {k: v for k, v in SLOT.items() if k != "banned_terms"}
        self.assertEqual(check("Calls the API. [web/Login.tsx:3]", plain), [])


if __name__ == "__main__":
    unittest.main()
