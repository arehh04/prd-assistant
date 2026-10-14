import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import zodschema

SCHEMA = r'''import { z } from "zod";
export const PeriodRegex = /^\d{4}-(0[1-9]|1[0-2])$/;
export const CalculatePayrollSchema = z.object({
  period: z
    .string()
    .regex(PeriodRegex, "Payroll period must be in YYYY-MM format (e.g. 2026-09)"),
  workerId: z.string().uuid("Invalid worker ID").optional(),
  name: z.string().min(2, "Too short, sorry").max(50),
  status: z.enum(["OPEN", "PAID"]).optional(),
  kind: PayrollStatusSchema.optional(),
  count: z.number().int().gte(1).lte(9).default(3),
  nick: z.string().transform((s) => s.trim()).nullable(),
});
export const PayrollQuerySchema = z.object({ period: z.string().optional() });
'''
CONTROLLER = '''export class PayrollController {
  @Get()
  async getPayrolls(
    @CurrentUser() user: AuthenticatedUser,
    @Query(new ZodValidationPipe(PayrollQuerySchema))
    query: PayrollQueryInput,
  ) {
    return 1;
  }

  @Get('summary')
  async getSummary(@Query('period') period: string) {}

  @Post('calculate')
  async calculate(@Body(new ZodValidationPipe(CalculatePayrollSchema)) body: X) {}

  @Post('dto')
  async dto(@Body() body: CreateThing) {}

  @Post('missing')
  async missing(@Body(new ZodValidationPipe(NoSuchSchema)) body: X) {}

  @Get(':id')
  async one(@Param('id', ParseUUIDPipe) id: string) {}
}
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class ZodSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schemas = zodschema.parse_schemas(SCHEMA, "packages/schemas/payroll.schema.ts")
        self.fields = {f["name"]: f for f in self.schemas["CalculatePayrollSchema"]["fields"]}

    def test_string_with_regex_and_message(self):
        f = self.fields["period"]
        self.assertEqual((f["type"], f["required"], f["pattern"]), ("string", True, "PeriodRegex"))
        self.assertEqual(f["messages"], ["Payroll period must be in YYYY-MM format (e.g. 2026-09)"])
        self.assertTrue(f["source"].startswith("packages/schemas/payroll.schema.ts:"))

    def test_format_optional_and_message(self):
        f = self.fields["workerId"]
        self.assertEqual((f["format"], f["required"], f["messages"]), ("uuid", False, ["Invalid worker ID"]))

    def test_min_max_with_comma_in_message(self):
        f = self.fields["name"]
        self.assertEqual((f["min"], f["max"], f["messages"]), (2, 50, ["Too short, sorry"]))

    def test_enum_ref_default_and_nullable(self):
        self.assertEqual(self.fields["status"]["one_of"], ["OPEN", "PAID"])
        self.assertEqual(self.fields["kind"]["type"], "ref:PayrollStatusSchema")
        count = self.fields["count"]
        self.assertEqual((count["required"], count["min"], count["max"]), (False, 1, 9))
        self.assertTrue(self.fields["nick"]["nullable"])
        self.assertIn("transform", self.fields["nick"]["other"])

    def test_schema_index_drops_ambiguous_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("a/x.schema.ts", "b/y.schema.ts"):
                p = Path(tmp) / rel
                p.parent.mkdir(parents=True)
                p.write_text('export const Dup = z.object({ a: z.string() });\n')
            (Path(tmp) / "c.schema.ts").write_text('export const Solo = z.object({ a: z.string() });\n')
            index = zodschema.SchemaIndex(tmp)
        self.assertIn("Solo", index.schemas)
        self.assertNotIn("Dup", index.schemas)
        self.assertIn("Dup", index.ambiguous)

    def test_hostile_unbalanced_input_does_not_hang_or_raise(self):
        zodschema.parse_schemas("const A = z.object({ a: z.string(" + "(" * 5000, "x.ts")


class NestRequestTests(unittest.TestCase):
    def setUp(self):
        self.schemas = zodschema.parse_schemas(SCHEMA, "s.ts")

    def rec(self, needle):
        return zodschema.read_request("c.ts", CONTROLLER, line_of(CONTROLLER, needle), self.schemas)

    def test_query_schema_through_the_pipe(self):
        r = self.rec("async getPayrolls(")
        self.assertEqual([(f["name"], f["location"]) for f in r["fields"]], [("period", "query")])
        self.assertEqual(r["not_read"], [])

    def test_named_query_param_without_a_schema(self):
        r = self.rec("async getSummary(")
        self.assertEqual([(f["name"], f["location"], f["required"]) for f in r["fields"]], [("period", "query", None)])

    def test_body_schema_fields(self):
        r = self.rec("async calculate(")
        self.assertEqual({f["name"] for f in r["fields"]}, set(self.fields_names()))
        self.assertTrue(all(f["location"] == "body" for f in r["fields"]))

    def fields_names(self):
        return [f["name"] for f in self.schemas["CalculatePayrollSchema"]["fields"]]

    def test_dto_class_and_missing_schema_are_not_read(self):
        self.assertIn("CreateThing", self.rec("async dto(")["not_read"][0])
        self.assertIn("NoSuchSchema", self.rec("async missing(")["not_read"][0])

    def test_path_param(self):
        r = self.rec("async one(")
        self.assertEqual([(f["name"], f["location"]) for f in r["fields"]], [("id", "path")])


if __name__ == "__main__":
    unittest.main()
