import unittest

from prd_assistant import ui_text

TSX = '''export function TeamsPage() {
  const [error, setError] = useState<string | null>(null)
  async function save() {
    try { await api.save() } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save team")
      toast.error("Could not save")
      console.error("debug only", err)
      throw new Error("internal failure")
    }
  }
  return (
    <div>
      <h1>Teams</h1>
      <p className="text-sm">Pick a team to continue.</p>
      <Label htmlFor="n">Team name</Label>
      <Input placeholder="e.g. Engineering recruiters" aria-label="Name field" />
      <Button type="submit">Create team</Button>
      <div role="alert">Something went wrong</div>
      <span className="text-destructive">Name is required</span>
      {error ? <p>{error}</p> : null}
      <p>Hello {"world"} again</p>
      <p>Don't worry, you're fine</p>
      <CardTitle>Account</CardTitle>
      <NavLink to="/home">Back home</NavLink>
    </div>
  )
}
'''


def find_line(content, needle):
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class JsxItemsTests(unittest.TestCase):
    def setUp(self):
        self.items = ui_text.extract_items(TSX, "src/TeamsPage.tsx")
        self.pairs = {(i["kind"], i["text"]) for i in self.items}

    def test_expected_items_are_found(self):
        expected = {
            ("heading", "Teams"), ("text", "Pick a team to continue."), ("label", "Team name"),
            ("placeholder", "e.g. Engineering recruiters"), ("title", "Name field"),
            ("button", "Create team"), ("message", "Something went wrong"), ("message", "Name is required"),
            ("message", "Failed to save team"), ("message", "Could not save"),
            ("text", "Hello"), ("text", "world"), ("text", "again"),
            ("heading", "Account"), ("button", "Back home"),
        }
        self.assertLessEqual(expected, self.pairs)

    def test_logging_and_error_constructors_are_not_messages(self):
        texts = {t for _, t in self.pairs}
        self.assertNotIn("debug only", texts)
        self.assertNotIn("internal failure", texts)

    def test_generics_are_not_mistaken_for_tags(self):
        texts = {t for _, t in self.pairs}
        self.assertFalse([t for t in texts if "null" in t or "string" in t])

    def test_apostrophes_in_text_do_not_corrupt_the_rest_of_the_file(self):
        self.assertIn(("text", "Don't worry, you're fine"), self.pairs)
        self.assertIn(("heading", "Account"), self.pairs)  # appears after the apostrophe line

    def test_lines_and_file(self):
        by = {(i["kind"], i["text"]): i for i in self.items}
        self.assertEqual(by[("heading", "Teams")]["line"], find_line(TSX, "<h1>"))
        self.assertEqual(by[("message", "Could not save")]["line"], find_line(TSX, "toast.error"))
        self.assertEqual(by[("placeholder", "e.g. Engineering recruiters")]["line"], find_line(TSX, "<Input"))
        self.assertEqual(by[("heading", "Teams")]["file"], "src/TeamsPage.tsx")

    def test_items_are_sorted_by_line_and_deduplicated(self):
        lines = [i["line"] for i in self.items]
        self.assertEqual(lines, sorted(lines))
        again = ui_text.extract_items("<p>Hi</p>\n<p>Hi</p>\n", "a.tsx")
        self.assertEqual([i["text"] for i in again], ["Hi"])

    def test_attribute_strings_that_are_not_visible_text_are_skipped(self):
        items = ui_text.extract_items('<a href="/x" className="btn big" id="q" data-x="y z">Go</a>\n', "a.tsx")
        self.assertEqual([(i["kind"], i["text"]) for i in items], [("button", "Go")])

    def test_empty_and_unreadable_text_is_fine(self):
        self.assertEqual(ui_text.extract_items("", "a.tsx"), [])
        self.assertEqual(ui_text.extract_items("const a = 1;\n", "a.ts"), [])


if __name__ == "__main__":
    unittest.main()
