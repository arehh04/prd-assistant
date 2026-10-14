import os
import tempfile
import time
import unittest
from pathlib import Path

from prd_assistant.dev import errors, roles, rules, source


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def facts_for(rel, line=1, method="GET"):
    return {"routes": [{"id": "r", "method": method, "path": "/x", "file": rel, "line": line, "source": f"{rel}:{line}",
                        "handler": {"id": "h", "source": f"{rel}:{line}"}}], "screens": []}


UI = {"screens": {}}
LINKS = {"routes": {"r": {"frontend": []}}}


class HostileFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_a_handler_file_that_is_secret_named_or_a_symlink_is_not_read_and_not_leaked(self):
        write(self.root, "api/credentials.ts", "export class C { async f() { throw new NotFoundException('TOPSECRET'); } }\n")
        write(self.outside, "x.ts", "export class C { async f() { throw new NotFoundException('OUTSIDE'); } }\n")
        os.symlink(self.outside / "x.ts", self.root / "api" / "link.ts")
        for rel in ("api/credentials.ts", "api/link.ts"):
            facts = facts_for(rel)
            r = roles.build(self.root, facts, UI, LINKS)["endpoints"]["r"]
            self.assertEqual(r["status"], "not_read", rel)
            req = rules.build(self.root, facts, UI, LINKS)["endpoints"]["r"]
            self.assertTrue(req["not_read"], rel)
            out = errors.build(self.root, facts, {"endpoints": {}}, None)
            self.assertEqual(out["messages"], [], rel)

    def test_deeply_nested_python_does_not_crash_or_hang(self):
        write(self.root, "api/deep.py", "async def f():\n    return " + "(" * 4000 + "1" + ")" * 4000 + "\n")
        started = time.monotonic()
        facts = facts_for("api/deep.py", 1)
        self.assertEqual(roles.build(self.root, facts, UI, LINKS)["endpoints"]["r"]["status"], "not_read")
        errors.build(self.root, facts, {"endpoints": {}}, None)
        self.assertLess(time.monotonic() - started, 5)

    def test_pathological_long_lines_stay_fast(self):
        write(self.root, "api/long.ts", "@Roles(" + "A," * 40000 + ")\nasync f() {}\n" + "// " + "x" * 500000)
        started = time.monotonic()
        r = roles.build(self.root, facts_for("api/long.ts", 2), UI, LINKS)["endpoints"]["r"]
        self.assertEqual((r["status"], r["roles"]), ("not_read", None))
        rules.build(self.root, facts_for("api/long.ts", 2), UI, LINKS)
        errors.build(self.root, facts_for("api/long.ts", 2), {"endpoints": {}}, None)
        self.assertLess(time.monotonic() - started, 5)

    def test_an_empty_or_unresolved_role_list_is_never_reported_as_nobody(self):
        write(self.root, "api/c.ts", "@Controller('x')\nexport class C {\n  @Roles(...NOT_THERE)\n  @Get()\n  async f() {}\n}\n")
        r = roles.build(self.root, facts_for("api/c.ts", 5), UI, LINKS)["endpoints"]["r"]
        self.assertEqual(r["status"], "not_read")
        self.assertIsNone(r["roles"])

    def test_undeclared_means_follows_the_stack_not_a_guess(self):
        write(self.root, "api/c.ts", "export class C {\n  @Get()\n  async f() {}\n}\n")
        write(self.root, "api/h.py", "from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get('/x')\nasync def f():\n    return 1\n")
        nest = roles.build(self.root, facts_for("api/c.ts", 3), UI, LINKS)["endpoints"]["r"]
        fast = roles.build(self.root, facts_for("api/h.py", 5), UI, LINKS)["endpoints"]["r"]
        self.assertEqual((nest["undeclared_means"], fast["undeclared_means"]), ("unknown", "open"))


class ReaderCrashTests(unittest.TestCase):
    def test_source_helpers_survive_garbage(self):
        for text in ("\x00" * 100, "(" * 100000, "'" * 100000, "{" * 100000):
            self.assertIsNone(source.paren_args(text, 0) if text.startswith("(") else None)
            source.split_args(text[:5000])
            source.scan_consts(text[:5000])


if __name__ == "__main__":
    unittest.main()
