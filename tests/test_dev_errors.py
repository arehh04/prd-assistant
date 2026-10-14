import sqlite3
import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import errors, pyast

PY = '''from fastapi import HTTPException


def helper(x):
    if not x:
        raise HTTPException(status_code=404, detail=f"Team {x} not found")


async def handler(id: str):
    if id == "a":
        raise HTTPException(409, "Name already taken")
    helper(id)
    raise HTTPException(status_code=422, detail=compute())
'''
DEPS = '''from fastapi import HTTPException


async def require_admin():
    raise HTTPException(status_code=403, detail="Admin access required")
'''
TS = '''export class C {
  async get(id: string) {
    if (!x) throw new NotFoundException(`Team ${id} not found`);
    if (y) throw new ForbiddenException("No access");
    throw new HttpException({ message: 'Custom' }, 418);
    throw new BadRequestException(buildMsg());
    throw new Error("internal failure");
  }
}
'''
PHP = r'''<?php
class C {
    public function show($id) {
        abort(404, 'Not found');
        abort_if($x, 403, "Nope $id");
        throw new ApiException('Conflict happened', 409);
        throw new DomainException($msg);
    }
}
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


def triple(msgs):
    return [(m["status"], m["kind"], m["text"]) for m in msgs]


class ExtractorTests(unittest.TestCase):
    def test_python_literal_template_dict_and_computed(self):
        tree = pyast.py_tree(PY)
        fn = errors.find_function(tree, line_of(PY, "async def handler"))
        msgs, unread = errors.py_messages("api/teams.py", fn, "handler")
        self.assertEqual(triple(msgs), [(409, "literal", "Name already taken")])
        self.assertEqual(unread, ["message is computed or not a plain string"])
        helper = errors.find_function(tree, line_of(PY, "def helper"))
        msgs, _ = errors.py_messages("api/teams.py", helper, "helper", helper="helper")
        self.assertEqual(triple(msgs), [(404, "template", "Team {…} not found")])
        self.assertEqual(msgs[0]["helper"], "helper")
        self.assertEqual(msgs[0]["source"], f"api/teams.py:{line_of(PY, 'raise HTTPException(status_code=404')}")

    def test_python_dict_detail_uses_the_message_key(self):
        tree = pyast.py_tree('def f():\n    raise HTTPException(403, {"code": "x", "message": "Not provisioned"})\n')
        msgs, _ = errors.py_messages("a.py", errors.find_function(tree, 1), "handler")
        self.assertEqual(triple(msgs), [(403, "literal", "Not provisioned")])

    def test_typescript(self):
        msgs, unread = errors.ts_messages("c.ts", TS, line_of(TS, "async get("), "handler")
        self.assertEqual(triple(msgs), [(404, "template", "Team {…} not found"), (403, "literal", "No access"),
                                        (418, "literal", "Custom")])
        self.assertEqual(len(unread), 2)

    def test_php(self):
        msgs, unread = errors.php_messages("C.php", PHP, line_of(PHP, "function show"), "handler")
        self.assertEqual(triple(msgs), [(404, "literal", "Not found"), (403, "template", "Nope {…}"),
                                        (409, "literal", "Conflict happened")])
        self.assertEqual(len(unread), 1)

    def test_hostile_unterminated_text_is_fast(self):
        import time
        started = time.monotonic()
        errors.ts_messages("c.ts", "async f() {" + "throw new NotFoundException(`" * 3000, 1, "handler")
        errors.php_messages("C.php", "<?php function f() {" + "abort(404, '" * 3000, 1, "handler")
        self.assertLess(time.monotonic() - started, 3)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for rel, text in (("api/teams.py", PY), ("api/dependencies.py", DEPS)):
            p = Path(self.root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        line = line_of(PY, "async def handler")
        self.facts = {"routes": [{"id": "r1", "method": "POST", "path": "/t", "file": "api/teams.py", "line": line - 1,
                                  "handler": {"id": "h1", "source": f"api/teams.py:{line}"}}]}
        self.roles = {"endpoints": {"r1": {"guards": [f"api/dependencies.py:{line_of(DEPS, 'async def require_admin')}"]}}}
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            "create table nodes(id text, kind text, name text, file_path text, start_line int);"
            "create table edges(source text, target text, kind text);")
        self.conn.execute("insert into nodes values('p1','function','helper','api/teams.py',?)",
                          (line_of(PY, "def helper"),))
        self.conn.execute("insert into edges values('h1','p1','calls')")

    def test_handler_helper_and_guard_messages_with_site_counts(self):
        out = errors.build(self.root, self.facts, self.roles, self.conn)
        got = sorted((m["via"], m["status"], m["text"]) for m in out["messages"])
        self.assertEqual(got, [("guard", 403, "Admin access required"), ("handler", 409, "Name already taken"),
                               ("helper", 404, "Team {…} not found")])
        self.assertTrue(all(m["route"] == "r1" for m in out["messages"]))
        self.assertEqual(out["sites"], {"total": 4, "attached": 3})
        self.assertEqual(out["unattached"], 1)
        self.assertEqual(out["not_read"], {"message is computed or not a plain string": 1})
        self.assertEqual(out["schema_version"], 1)

    def test_without_a_codegraph_index_helpers_are_reported_not_skipped_silently(self):
        out = errors.build(self.root, self.facts, self.roles, None)
        self.assertEqual({m["via"] for m in out["messages"]}, {"guard", "handler"})
        self.assertEqual(out["not_read"].get("no CodeGraph index: helper messages were not read"), 1)

    def test_callees_excludes_tests_and_the_handler_itself(self):
        self.conn.execute("insert into nodes values('t1','function','t','tests/test_x.py',3)")
        self.conn.execute("insert into edges values('h1','t1','calls')")
        self.conn.execute("insert into edges values('h1','h1','calls')")
        self.conn.execute("insert into nodes values('h1','function','handler','api/teams.py',9)")
        names = [r["name"] for r in errors.callees(self.conn, "h1")]
        self.assertEqual(names, ["helper"])

    def test_reader_crash_becomes_not_read(self):
        import unittest.mock as mock
        with mock.patch("prd_assistant.dev.errors.py_messages", side_effect=RecursionError):
            out = errors.build(self.root, self.facts, self.roles, None)
        self.assertEqual(out["not_read"].get("reader error: RecursionError"), 2)   # the handler job and the guard job


if __name__ == "__main__":
    unittest.main()
