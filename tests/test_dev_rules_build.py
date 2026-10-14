import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import rules

CONTROLLER = '''export class C {
  @Post('calculate')
  async calculate(@Body(new ZodValidationPipe(TeamSchema)) body: X) {}

  @Post('action')
  async action() {}

  @Post('dto')
  async dto(@Body() body: Thing) {}
}
'''
SCHEMA = 'export const TeamSchema = z.object({ title: z.string().max(60), size: z.number().min(1) });\n'
FORM = 'export const F = () => (<form><input name="title" maxLength={50} /><input name="size" min="2" /></form>);\n'


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class RulesBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "api/c.controller.ts", CONTROLLER)
        write(self.root, "pk/team.schema.ts", SCHEMA)
        write(self.root, "web/F.tsx", FORM)
        h = lambda needle: {"source": f"api/c.controller.ts:{line_of(CONTROLLER, needle)}"}
        self.facts = {"routes": [
            {"id": "r-calc", "method": "POST", "path": "/calculate", "file": "api/c.controller.ts", "line": 2, "handler": h("async calculate")},
            {"id": "r-act", "method": "POST", "path": "/action", "file": "api/c.controller.ts", "line": 5, "handler": h("async action")},
            {"id": "r-dto", "method": "POST", "path": "/dto", "file": "api/c.controller.ts", "line": 8, "handler": h("async dto")},
            {"id": "r-get", "method": "GET", "path": "/g", "file": "api/c.controller.ts", "line": 1, "handler": None},
        ], "screens": [{"id": "s1", "path": "/f", "file": "web/router.tsx", "line": 1}]}
        self.ui = {"screens": {"s1": {"files": ["web/F.tsx"]}}}
        self.links = {"routes": {"r-calc": {"frontend": [{"file": "web/F.tsx", "line": 1}]}, "r-act": {"frontend": []},
                                 "r-dto": {"frontend": []}, "r-get": {"frontend": []}}}

    def test_counts_and_endpoint_records(self):
        out = rules.build(self.root, self.facts, self.ui, self.links)
        self.assertEqual(out["schema_version"], 1)
        self.assertEqual({f["name"] for f in out["endpoints"]["r-calc"]["fields"]}, {"title", "size"})
        self.assertEqual(out["endpoints"]["r-act"]["fields"], [])
        self.assertEqual(out["counts"], {"routes": 4, "takes_input": 3, "read": 2, "not_read": 1})

    def test_form_limits_that_differ_from_the_endpoint_are_flagged(self):
        out = rules.build(self.root, self.facts, self.ui, self.links)
        got = {(m["field"], m["kind"]): (m["form_value"], m["endpoint_value"]) for m in out["mismatches"]}
        self.assertEqual(got, {("title", "max_length"): (50, 60), ("size", "min"): (2, 1)})
        m = out["mismatches"][0]
        self.assertEqual((m["screen"], m["endpoint"]), ("s1", "r-calc"))

    def test_equal_limits_and_unjoined_screens_make_no_claim(self):
        self.assertEqual(rules.mismatches({"s": {"fields": [{"field": "a", "maxlength": 5, "source": "x:1"}]}},
                                          {"e": {"fields": [{"name": "a", "type": "string", "max": 5, "source": "y:1"}]}},
                                          {"s": ["e"]}), [])
        self.assertEqual(rules.mismatches({"s": {"fields": [{"field": "a", "maxlength": 5, "source": "x:1"}]}},
                                          {"e": {"fields": [{"name": "a", "type": "string", "max": 9, "source": "y:1"}]}},
                                          {"s": []}), [])

    def test_a_reader_crash_becomes_not_read(self):
        import unittest.mock as mock
        with mock.patch("prd_assistant.dev.zodschema.read_request", side_effect=RecursionError):
            out = rules.build(self.root, self.facts, self.ui, self.links)
        self.assertIn("RecursionError", out["endpoints"]["r-calc"]["not_read"][0])


if __name__ == "__main__":
    unittest.main()
