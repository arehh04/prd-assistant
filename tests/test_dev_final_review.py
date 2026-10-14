"""Regression tests for the slice 3b final review findings (C1-C4, I1-I9)."""
import ast
import json
import tempfile
import time
import unittest
from pathlib import Path

from prd_assistant import devguide, draft
from prd_assistant.dev import (errors, pyast, roles, roles_fastapi, roles_front, roles_laravel, roles_nest,
                               rules_pydantic, source, zodschema)


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


DEPS = '''from fastapi import Depends, HTTPException, Security
async def get_user(token=Depends(oauth2_scheme)):
    return token
async def verify(t):
    if bad(t):
        raise InvalidToken()
async def get_u2(t=Depends(verify)):
    return t
async def owner_only(item, user):
    if user.id != item.owner:
        raise HTTPException(status_code=403, detail="Not yours")
async def blocked(req):
    if req.client.host not in BLOCK:
        raise HTTPException(status_code=403, detail="Blocked")
'''
ROUTES = '''from fastapi import APIRouter, Depends, Security
router = APIRouter()

@router.get("/a", dependencies=[Depends(require_role("admin"))])
async def a():
    return 1

@router.get("/b")
async def b(x=Depends(require_role("admin"))):
    return 1

@router.get("/e")
async def e(x=Security(get_user, scopes=["a"])):
    return 1

@router.get("/v")
async def v(u=Depends(get_u2)):
    return 1

@router.get("/o")
async def o(w=Depends(owner_only)):
    return 1

@router.get("/k")
async def k(w=Depends(blocked)):
    return 1
'''


class FastApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        write(self.tmp.name, "api/deps.py", DEPS)
        write(self.tmp.name, "api/routes.py", ROUTES)
        self.idx = pyast.PyIndex(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def rec(self, needle):
        return roles_fastapi.read_roles("api/routes.py", self.idx.trees["api/routes.py"], ROUTES,
                                        line_of(ROUTES, needle), self.idx)

    def test_c1_factory_dependencies_and_security_scopes_are_not_reported_as_open(self):
        for needle in ("async def a(", "async def b(", "async def e("):
            r = self.rec(needle)
            self.assertEqual(r["status"], "not_read", needle)
            self.assertIsNone(r["roles"])

    def test_i2_a_dependency_that_raises_something_unrecognised_is_not_plumbing(self):
        self.assertEqual(self.rec("async def v(")["status"], "not_read")

    def test_i3_a_403_guard_that_is_not_about_roles_is_not_a_role_list(self):
        for needle in ("async def o(", "async def k("):
            r = self.rec(needle)
            self.assertNotEqual(r["status"], "read", needle)
            self.assertFalse(r["roles"], needle)


class NestAndLaravelPartialMatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.index = source.ConstIndex(self.tmp.name)

    def nest(self, deco):
        text = f"export class C {{\n  {deco}\n  @Get()\n  async f() {{}}\n}}\n"
        return roles_nest.read_roles("c.ts", text, line_of(text, "async f()"), self.index, {})

    def test_c2_nest_unparseable_or_partial_or_empty_role_lists_are_not_read(self):
        for deco in ("@Roles(getRoles())", "@Roles(Role.Admin, compute())", "@Roles(`a${x}`)", "@Roles()"):
            r = self.nest(deco)
            self.assertEqual((r["status"], r["roles"]), ("not_read", None), deco)

    def laravel(self, mw):
        text = f"<?php\nRoute::get('/a', [A::class, 'b']){mw};\n"
        return roles_laravel.read_roles("routes/api.php", text, 2)

    def test_c2_laravel_dynamic_or_overridden_middleware_is_not_read(self):
        for mw in ("->middleware(['role:'.$x])", "->middleware(['auth', $mw])",
                   "->middleware('role:admin')->withoutMiddleware('role:admin')"):
            self.assertEqual(self.laravel(mw)["status"], "not_read", mw)

    def test_c2_laravel_pipe_separated_roles(self):
        self.assertEqual(self.laravel("->middleware('role:admin|editor')")["roles"], ["admin", "editor"])


class MismatchTests(unittest.TestCase):
    def test_c3_an_empty_role_list_never_makes_a_mismatch(self):
        self.assertEqual(roles.mismatches({"s": {"status": "read", "roles": ["Admin"]}},
                                          {"e": {"status": "read", "roles": []}}, {"s": ["e"]}), [])

    def test_i7_mismatch_wording_says_how_the_screen_was_joined(self):
        m = roles.mismatches({"s": {"status": "read", "roles": ["A", "B"]}},
                             {"e": {"status": "read", "roles": ["A"]}}, {"s": ["e"]})
        self.assertIn("2 hops", m[0]["detail"])


class StaleOutputTests(unittest.TestCase):
    STALE_DEV = ("scaffold.md", "slots.template.json", "manifest.json", "dev_summary.json", "developer-guide.md",
                 "roles.json", "form_rules.json", "error_messages.json", "dev_gate.json", "dev_gate.md")
    STALE_GUIDE = ("scaffold.md", "slots.template.json", "manifest.json", "guide_summary.json", "client-guide.md")

    def test_c4_early_failures_remove_older_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = Path(tmp) / "repo", Path(tmp) / "out"
            repo.mkdir()
            out.mkdir()
            (out / "facts.json").write_text(json.dumps({"meta": {"repo": "/somewhere/else"}, "routes": [], "screens": []}))
            (out / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
            for sub, names, fn in (("dev", self.STALE_DEV, draft.dev_prepare), ("guide", self.STALE_GUIDE, draft.guide_prepare)):
                (out / sub).mkdir()
                for name in names:
                    (out / sub / name).write_text("old")
                with self.assertRaises(ValueError):
                    fn(repo, out)
                for name in names:
                    self.assertFalse((out / sub / name).exists(), f"{sub}/{name}")


class SlowInputTests(unittest.TestCase):
    def test_i1_quadratic_scans_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/nav.ts", "".join(f"  path: '/a{i}',\n" for i in range(12000)) + "const roles = 1;\n")
            write(tmp, "web/consts.ts", "".join(f"const A{i} = [\n" for i in range(40000)))
            write(tmp, "web/imports.ts", "".join("import {a,\n" for _ in range(60000)) + "Roles(")
            started = time.monotonic()
            index = source.ConstIndex(tmp)
            roles_front.nav_tables(tmp, index)
            roles_nest.build_aliases(tmp)
            self.assertLess(time.monotonic() - started, 8)

    def test_i1_many_laravel_routes_are_not_quadratic(self):
        lines = ["<?php", "Route::middleware('role:admin')->group(function (): void {"]
        lines += [f"    Route::get('/r{i}', [C::class, 'm{i}']);" for i in range(2500)]
        lines += ["});"]
        text = "\n".join(lines) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "routes/api.php", text)
            write(tmp, "app/C.php", "<?php\nclass C {\n    public function m() { return 1; }\n}\n")
            facts = {"routes": [{"id": f"r{i}", "method": "GET", "path": f"/r{i}", "file": "routes/api.php",
                                 "line": 3 + i, "source": f"routes/api.php:{3 + i}",
                                 "handler": {"source": "app/C.php:3"}} for i in range(2500)], "screens": []}
            started = time.monotonic()
            out = roles.build(tmp, facts, {"screens": {}}, {"routes": {}})
            self.assertLess(time.monotonic() - started, 8)
            self.assertEqual(out["endpoints"]["r1200"]["roles"], ["admin"])


class RequestReaderTests(unittest.TestCase):
    def test_i5_annotated_depends_is_not_a_body_model(self):
        models = "class User(BaseModel):\n    id: int\n    password_hash: str\n"
        routes = "from typing import Annotated\n\n@router.get('/me')\nasync def me(u: Annotated[User, Depends(get_user)]):\n    return u\n"
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "api/models.py", models)
            write(tmp, "api/routes.py", routes)
            idx = pyast.PyIndex(tmp)
            r = rules_pydantic.read_request("api/routes.py", idx.trees["api/routes.py"], line_of(routes, "async def me"), "/me", idx)
        self.assertEqual(r["fields"], [])

    def test_i6_unrecognised_nest_parameter_decorators_are_not_read(self):
        text = "export class C {\n  @Post()\n  async a(@Body(new ValidationPipe()) dto: X, @Req() req) {}\n}\n"
        r = zodschema.read_request("c.ts", text, line_of(text, "async a("), {})
        self.assertGreaterEqual(len(r["not_read"]), 2)

    def test_i8_zod_coerce_and_exclusive_bounds(self):
        schemas = zodschema.parse_schemas("export const S = z.object({ a: z.coerce.number().optional(), b: z.number().gt(0), "
                                          "c: z.string().min(1).foo.bar })", "s.ts")
        f = {x["name"]: x for x in schemas["S"]["fields"]}
        self.assertEqual((f["a"]["type"], f["a"]["required"]), ("number", False))
        self.assertEqual((f["b"]["min"], f["b"].get("gt")), (None, 0))
        self.assertIsNone(f["c"]["required"])      # the chain could not be fully parsed


class RenderingTests(unittest.TestCase):
    def test_i9_unknown_status_renders_as_a_question_mark(self):
        facts = {"routes": [{"id": "r", "method": "GET", "path": "/x", "source": "a.py:1"}], "screens": []}
        rl = {"counts": {"routes": 1, "read": 1, "public": 0, "undeclared": 0, "not_read": 0}, "role_names": [],
              "endpoints": {"r": {"status": "read", "roles": ["A"], "authenticated": False, "via": [], "source": "a.py:1"}},
              "screens": {}, "joined": {}, "mismatches": []}
        ru = {"endpoints": {"r": {"fields": [], "not_read": []}}, "forms": {}, "mismatches": [],
              "counts": {"routes": 1, "takes_input": 0, "read": 0, "not_read": 0}}
        er = {"messages": [{"route": "r", "status": None, "kind": "literal", "text": "Nope", "via": "handler", "source": "a.py:3"}],
              "sites": {"total": 1, "attached": 1}, "unattached": 0, "not_read": {}, "counts": {"messages": 1}}
        text, _ = devguide.build(facts, {"verdict": "PASS"}, rl, ru, er, devguide.dev_gate(rl, ru, er), "d", "2026-01-01")
        self.assertNotIn("None Nope", text)
        self.assertIn("? Nope", text)

    def test_i4_undeclared_is_not_stated_as_a_bare_fact(self):
        for means in ("open", "unknown"):
            who = devguide._who({"status": "undeclared", "undeclared_means": means})
            self.assertIn("found", who)
        self.assertIn("global guard", devguide._who({"status": "undeclared", "undeclared_means": "denied"}))


if __name__ == "__main__":
    unittest.main()
