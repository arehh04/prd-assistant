import unittest

from prd_assistant.mask import line_of, mask, match_brace


class MaskTests(unittest.TestCase):
    def test_length_and_newlines_are_preserved(self):
        src = "a // b\nc /* x\ny */ d 'q\nr'"
        out = mask(src)
        self.assertEqual(len(out), len(src))
        self.assertEqual(out.count("\n"), src.count("\n"))

    def test_line_comment_is_blanked(self):
        out = mask("a // b")
        self.assertEqual(len(out), len("a // b"))
        self.assertEqual(out.strip(), "a")

    def test_string_content_is_blanked_but_quotes_stay(self):
        self.assertEqual(mask("x = 'a//b'"), "x = '" + " " * 4 + "'")

    def test_escaped_quote_does_not_end_the_string(self):
        out = mask("'a\\'b' // c")
        self.assertTrue(out.startswith("'"))
        self.assertNotIn("c", out)

    def test_hash_comments_only_when_asked_and_attributes_survive(self):
        src = "#[Attr]\n# note\ncode"
        self.assertEqual(mask(src), src)
        out = mask(src, hash_comments=True)
        self.assertTrue(out.startswith("#[Attr]"))
        self.assertNotIn("note", out)
        self.assertIn("code", out)

    def test_line_of(self):
        text = "a\nb\nc"
        self.assertEqual(line_of(text, 0), 1)
        self.assertEqual(line_of(text, 2), 2)
        self.assertEqual(line_of(text, 4), 3)

    def test_match_brace(self):
        m = mask("f({ a: { b: 1 }, c: '}' })")
        start = m.index("{")
        self.assertEqual(match_brace(m, start), len(m) - 2)
        self.assertEqual(match_brace("{ unbalanced", 0), len("{ unbalanced") - 1)

    def test_comments_only_mode_keeps_string_contents(self):
        out = mask("x = 'a//b' // c\n", blank_strings=False)
        self.assertTrue(out.startswith("x = 'a//b'"))
        self.assertNotIn("c", out)
        self.assertEqual(len(out), len("x = 'a//b' // c\n"))

    def test_apostrophe_between_letters_is_text_when_asked(self):
        src = "<p>Don't stop</p> // note\n"
        with_flag = mask(src, apostrophe_in_words=True)
        self.assertIn("Don't stop</p>", with_flag)
        self.assertNotIn("note", with_flag)
        default = mask(src)
        self.assertNotIn("stop", default)  # without the flag the apostrophe opens a "string" that swallows the line

    def test_a_real_string_after_punctuation_is_still_a_string(self):
        out = mask("x = ['a', 'b'] // c\n", apostrophe_in_words=True)
        self.assertEqual(out.count("'"), 4)
        self.assertNotIn("a", out.replace("x", ""))  # string contents are blanked


if __name__ == "__main__":
    unittest.main()
