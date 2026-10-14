import unittest

from prd_assistant import ui_text

VUE = '''<template>
  <div>
    <!-- <h3>Hidden comment</h3> -->
    <h2>Branches</h2>
    <p>Branch admins see their own branches.</p>
    <input placeholder="Search branches" />
    <button @click="a > b" :title="dynamicTitle">Add branch</button>
    <p class="error-text">Could not load branches</p>
    <span>{{ count }} total</span>
    <p>Don't forget to save</p>
  </div>
</template>

<script setup>
const x = ref(0)
notify("Saved branch")
console.error("not shown")
</script>
'''


def find_line(content, needle):
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class VueItemsTests(unittest.TestCase):
    def setUp(self):
        self.items = ui_text.extract_items(VUE, "web/src/views/BranchesView.vue")
        self.pairs = {(i["kind"], i["text"]) for i in self.items}

    def test_expected_items(self):
        expected = {("heading", "Branches"), ("text", "Branch admins see their own branches."),
                    ("placeholder", "Search branches"), ("button", "Add branch"),
                    ("message", "Could not load branches"), ("text", "total"),
                    ("text", "Don't forget to save"), ("message", "Saved branch")}
        self.assertLessEqual(expected, self.pairs)

    def test_comments_dynamic_attributes_and_logging_are_skipped(self):
        texts = {t for _, t in self.pairs}
        self.assertNotIn("Hidden comment", texts)
        self.assertNotIn("not shown", texts)
        self.assertNotIn("dynamicTitle", texts)

    def test_lines_are_file_lines(self):
        by = {(i["kind"], i["text"]): i for i in self.items}
        self.assertEqual(by[("heading", "Branches")]["line"], find_line(VUE, "<h2>"))
        self.assertEqual(by[("message", "Saved branch")]["line"], find_line(VUE, "notify("))
        self.assertEqual(by[("placeholder", "Search branches")]["line"], find_line(VUE, "<input"))

    def test_a_file_without_a_template_is_fine(self):
        self.assertEqual(ui_text.extract_items("<script>\nconst a = 1\n</script>\n", "a.vue"), [])
        self.assertEqual(ui_text.extract_items("", "a.vue"), [])


class VueCalibrationFindingsTests(unittest.TestCase):
    def test_ternary_strings_in_interpolations_and_library_attributes(self):
        text = ("<template>\n  <button>{{ busy ? 'Signing out…' : 'Log out' }}</button>\n"
                "  <Button label=\"New\" />\n  <Column header=\"Code\" />\n</template>\n")
        got = {(i["kind"], i["text"]) for i in ui_text.extract_items(text, "a.vue")}
        self.assertLessEqual({("button", "Signing out…"), ("button", "Log out"), ("button", "New"), ("label", "Code")}, got)


if __name__ == "__main__":
    unittest.main()
