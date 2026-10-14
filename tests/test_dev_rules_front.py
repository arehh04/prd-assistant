import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import rules_front, zodschema

FORM_TSX = '''import { zodResolver } from "@hookform/resolvers/zod";
export function F() {
  const form = useForm({ resolver: zodResolver(TeamSchema) });
  return (
    <form>
      <input name="title" required maxLength={50} minLength="2" />
      <Input {...register("email")} type="email" pattern="[a-z]+" />
      <textarea id="notes" maxlength="500"></textarea>
      <input placeholder="no name here" />
      {/* <input name="commented" required /> */}
    </form>
  );
}
'''
FORM_VUE = '''<template>
  <input v-model="form.code" required maxlength="10" />
  <!-- <input name="gone" required /> -->
</template>
'''
TEAM_SCHEMA = 'export const TeamSchema = z.object({ title: z.string().max(40), size: z.number().min(1) });\n'


class FormsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for rel, text in (("web/F.tsx", FORM_TSX), ("web/F.vue", FORM_VUE), ("web/team.schema.ts", TEAM_SCHEMA)):
            p = Path(self.root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.schemas = zodschema.SchemaIndex(self.root).schemas

    def test_html_attributes_for_jsx_and_vue(self):
        forms = rules_front.read_forms(self.root, ["web/F.tsx", "web/F.vue"], self.schemas)
        by = {f["field"]: f for f in forms["fields"] if not f.get("from_schema")}
        self.assertEqual((by["title"]["required"], by["title"]["maxlength"], by["title"]["minlength"]), (True, 50, 2))
        self.assertEqual((by["email"]["type"], by["email"]["pattern"]), ("email", "[a-z]+"))
        self.assertEqual(by["notes"]["maxlength"], 500)
        self.assertEqual((by["code"]["required"], by["code"]["maxlength"]), (True, 10))
        self.assertNotIn("commented", by)
        self.assertNotIn("gone", by)
        self.assertEqual(forms["unnamed"], 1)

    def test_zod_resolver_schema_fields(self):
        forms = rules_front.read_forms(self.root, ["web/F.tsx"], self.schemas)
        self.assertEqual(forms["schemas"], ["TeamSchema"])
        by = {f["field"]: f for f in forms["fields"] if f.get("from_schema")}
        self.assertEqual((by["title"]["maxlength"], by["size"]["min"]), (40, 1))

    def test_unreadable_files_are_skipped(self):
        forms = rules_front.read_forms(self.root, ["web/missing.tsx"], self.schemas)
        self.assertEqual(forms, {"fields": [], "schemas": [], "unnamed": 0})

    def test_hostile_unclosed_tags_are_fast(self):
        import time
        p = Path(self.root) / "web/H.tsx"
        p.write_text("<input " * 6000)
        started = time.monotonic()
        rules_front.read_forms(self.root, ["web/H.tsx"], self.schemas)
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
