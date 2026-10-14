import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import roles

CONTROLLER = '''@Controller('payroll')
export class PayrollController {
  @Get()
  @Authenticated()
  async list() {}

  @Post('calculate')
  @AdminOnly()
  async calculate() {}
}
'''
DECORATORS = "export const Authenticated = () => Roles(...ALL_ROLES);\nexport const AdminOnly = () => Roles(...ADMIN_ONLY);\n"
TYPES = 'export const ALL_ROLES = ["WORKER", "ADMIN"];\nexport const ADMIN_ONLY = ["ADMIN"];\n'
NAV = 'const N = [{ to: "/payroll", roles: NAV_ALL }, { to: "/team", roles: ADMIN_ONLY }];\nconst NAV_ALL = ["Worker", "admin"];\n'


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "api/payroll.controller.ts", CONTROLLER)
        write(self.root, "api/roles.decorator.ts", DECORATORS)
        write(self.root, "packages/types/roles.ts", TYPES)
        write(self.root, "web/src/nav.ts", NAV)
        write(self.root, "web/src/pay.tsx", "export const x = 1;\n")
        self.facts = {"routes": [
            {"id": "r-list", "method": "GET", "path": "/payroll", "file": "api/payroll.controller.ts", "line": 3,
             "handler": {"source": f"api/payroll.controller.ts:{line_of(CONTROLLER, 'async list()')}"}},
            {"id": "r-calc", "method": "POST", "path": "/payroll/calculate", "file": "api/payroll.controller.ts", "line": 7,
             "handler": {"source": f"api/payroll.controller.ts:{line_of(CONTROLLER, 'async calculate()')}"}},
            {"id": "r-none", "method": "GET", "path": "/x", "file": "api/payroll.controller.ts", "line": 1, "handler": None},
            {"id": "r-php", "method": "GET", "path": "/y", "file": "x.rb", "line": 1, "handler": {"source": "x.rb:1"}},
        ], "screens": [
            {"id": "s-pay", "path": "/payroll", "file": "web/src/router.tsx", "line": 1},
            {"id": "s-team", "path": "/team", "file": "web/src/router.tsx", "line": 2},
        ]}
        self.ui = {"screens": {"s-pay": {"files": ["web/src/pay.tsx"]}, "s-team": {"files": []}}}
        self.links = {"routes": {"r-list": {"frontend": []}, "r-calc": {"frontend": [{"file": "web/src/pay.tsx", "line": 1}]},
                                 "r-none": {"frontend": []}, "r-php": {"frontend": []}}}

    def test_endpoints_screens_and_counts(self):
        out = roles.build(self.root, self.facts, self.ui, self.links)
        self.assertEqual(out["schema_version"], 1)
        self.assertEqual(out["endpoints"]["r-list"]["roles"], ["WORKER", "ADMIN"])
        self.assertEqual(out["endpoints"]["r-calc"]["roles"], ["ADMIN"])
        self.assertEqual(out["endpoints"]["r-none"]["status"], "not_read")
        self.assertEqual(out["endpoints"]["r-php"]["status"], "not_read")
        self.assertEqual(out["screens"]["s-pay"]["roles"], ["Worker", "admin"])
        self.assertEqual(out["counts"], {"routes": 4, "read": 2, "public": 0, "undeclared": 0, "not_read": 2})
        self.assertEqual(out["role_names"], sorted(set(["WORKER", "ADMIN", "Worker", "admin"])))

    def test_mismatch_names_the_role_the_endpoint_refuses_ignoring_case(self):
        out = roles.build(self.root, self.facts, self.ui, self.links)
        self.assertEqual(len(out["mismatches"]), 1)
        m = out["mismatches"][0]
        self.assertEqual((m["screen"], m["endpoint"], m["refused_roles"]), ("s-pay", "r-calc", ["Worker"]))

    def test_no_claim_when_a_side_is_not_read_or_unjoined(self):
        self.assertEqual(roles.mismatches({"s": {"status": "not_read", "roles": None}},
                                          {"e": {"status": "read", "roles": ["A"]}}, {"s": ["e"]}), [])
        self.assertEqual(roles.mismatches({"s": {"status": "read", "roles": ["A"]}},
                                          {"e": {"status": "undeclared", "roles": None}}, {"s": ["e"]}), [])
        self.assertEqual(roles.mismatches({"s": {"status": "read", "roles": ["A"]}},
                                          {"e": {"status": "read", "roles": ["B"]}}, {"s": []}), [])

    def test_a_reader_crash_becomes_not_read(self):
        import unittest.mock as mock
        with mock.patch("prd_assistant.dev.roles_nest.read_roles", side_effect=RecursionError):
            out = roles.build(self.root, self.facts, self.ui, self.links)
        self.assertEqual(out["endpoints"]["r-list"]["status"], "not_read")
        self.assertIn("RecursionError", out["endpoints"]["r-list"]["reason"])


if __name__ == "__main__":
    unittest.main()
