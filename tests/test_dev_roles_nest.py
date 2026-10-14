import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import roles_nest, source

CONTROLLER = '''import { Controller, Get } from '@nestjs/common';

@Controller('payroll')
export class PayrollController {
  @Get()
  @Authenticated()
  async list() {}

  @Post('calculate')
  @FinanceWrite()
  async calculate() {}

  @Get('open')
  @Public()
  async open() {}

  @Get('nothing')
  @Mystery()
  async nothing() {}

  @Roles('ADMIN', Role.MANAGER)
  @Get('direct')
  async direct() {}

  @Get('broken')
  @Unresolved()
  async broken() {}
}
'''
DECORATORS = '''import { ALL_ROLES as ALL, MONEY_WRITE } from "@urus/types";
export const Authenticated = () => Roles(...ALL);
export const FinanceWrite = () => Roles(...MONEY_WRITE);
export const Unresolved = () => Roles(...NOT_DEFINED);
'''
TYPES = '''export const ALL_ROLES: readonly UserRole[] = ["WORKER", "ADMIN"];
export const MONEY_WRITE = ["FINANCE", "ADMIN"] as const;
'''
GUARD = '''@Injectable()
export class RolesGuard {
  canActivate(context) {
    if (!requiredRoles || requiredRoles.length === 0) {
      throw new ForbiddenException("no policy");
    }
  }
}
'''
APP_MODULE = "providers: [{ provide: APP_GUARD, useClass: RolesGuard }]\n"


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class NestRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "api/payroll.controller.ts", CONTROLLER)
        write(self.root, "api/roles.decorator.ts", DECORATORS)
        write(self.root, "packages/types/roles.ts", TYPES)
        self.index = source.ConstIndex(self.root)
        self.aliases = roles_nest.build_aliases(self.root)

    def rec(self, needle):
        return roles_nest.read_roles("api/payroll.controller.ts", CONTROLLER, line_of(CONTROLLER, needle),
                                     self.index, self.aliases)

    def test_alias_decorator_resolves_through_import_rename_and_constant(self):
        r = self.rec("async list()")
        self.assertEqual((r["status"], r["roles"]), ("read", ["WORKER", "ADMIN"]))
        self.assertIn("@Authenticated()", r["via"][0])
        self.assertTrue(r["source"].startswith("api/payroll.controller.ts:"))

    def test_second_alias_and_direct_roles(self):
        self.assertEqual(self.rec("async calculate()")["roles"], ["FINANCE", "ADMIN"])
        self.assertEqual(self.rec("async direct()")["roles"], ["ADMIN", "MANAGER"])

    def test_public(self):
        r = self.rec("async open()")
        self.assertEqual((r["status"], r["roles"]), ("public", None))

    def test_unknown_decorator_is_undeclared_and_listed(self):
        r = self.rec("async nothing()")
        self.assertEqual(r["status"], "undeclared")
        self.assertIn("Mystery", r["decorators"])
        self.assertEqual(r["undeclared_means"], "unknown")

    def test_unresolved_role_list_is_not_read_never_an_empty_list(self):
        r = self.rec("async broken()")
        self.assertEqual(r["status"], "not_read")
        self.assertIsNone(r["roles"])
        self.assertIn("Unresolved", r["reason"])

    def test_class_level_roles_apply_and_method_overrides(self):
        text = "@Roles('ADMIN')\n@Controller('x')\nexport class C {\n  @Get()\n  async a() {}\n\n  @Public()\n  async b() {}\n}\n"
        a = roles_nest.read_roles("c.ts", text, line_of(text, "async a()"), self.index, self.aliases)
        b = roles_nest.read_roles("c.ts", text, line_of(text, "async b()"), self.index, self.aliases)
        self.assertEqual((a["status"], a["roles"]), ("read", ["ADMIN"]))
        self.assertEqual(b["status"], "public")

    def test_fail_closed_is_read_from_the_guard(self):
        self.assertEqual(roles_nest.fail_closed(self.root), "unknown")
        write(self.root, "api/roles.guard.ts", GUARD)
        write(self.root, "api/app.module.ts", APP_MODULE)
        self.assertEqual(roles_nest.fail_closed(self.root), "denied")
        r = roles_nest.read_roles("api/payroll.controller.ts", CONTROLLER, line_of(CONTROLLER, "async nothing()"),
                                  self.index, self.aliases, fail_closed="denied")
        self.assertEqual(r["undeclared_means"], "denied")

    def test_unterminated_roles_arguments_are_not_read_never_an_empty_list(self):
        text = "export class C {\n  @Roles('ADMIN'\n  @Get()\n  async f() {}\n}\n"
        r = roles_nest.read_roles("c.ts", text, line_of(text, "async f()"), self.index, self.aliases)
        self.assertEqual((r["status"], r["roles"]), ("not_read", None))

    def test_duplicate_alias_names_are_dropped(self):
        write(self.root, "other/dup.ts", "export const Authenticated = () => Roles('X');\n")
        self.assertNotIn("Authenticated", roles_nest.build_aliases(self.root))


if __name__ == "__main__":
    unittest.main()
