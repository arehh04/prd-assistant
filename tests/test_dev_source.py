import os
import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import pyast, source


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class ReadSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_a_normal_file(self):
        write(self.root, "app/a.py", "x = 1\n")
        self.assertEqual(source.read_source(self.root, "app/a.py"), "x = 1\n")

    def test_refuses_secret_names_unknown_suffixes_and_missing_files(self):
        write(self.root, ".env", "A=1\n")
        write(self.root, "app/credentials.py", "KEY = 1\n")
        write(self.root, "app/data.json", "{}")
        for rel in (".env", "app/credentials.py", "app/data.json", "app/none.py"):
            self.assertIsNone(source.read_source(self.root, rel), rel)

    def test_refuses_symlinks_and_paths_that_leave_the_repo(self):
        write(self.outside, "x.py", "SECRET = 1\n")
        os.symlink(self.outside / "x.py", self.root / "link.py")
        os.symlink(self.outside, self.root / "dir")
        self.assertIsNone(source.read_source(self.root, "link.py"))
        self.assertIsNone(source.read_source(self.root, "dir/x.py"))
        self.assertIsNone(source.read_source(self.root, "../outside/x.py"))

    def test_refuses_oversize_files(self):
        write(self.root, "big.py", "#" * (source.MAX_FILE_BYTES + 1))
        self.assertIsNone(source.read_source(self.root, "big.py"))


class HelperTests(unittest.TestCase):
    def test_split_source(self):
        self.assertEqual(source.split_source("a/b.py:12"), ("a/b.py", 12))

    def test_line_start(self):
        text = "a\nbb\nccc"
        self.assertEqual(source.line_start(text, 1), 0)
        self.assertEqual(source.line_start(text, 3), 5)
        self.assertEqual(source.line_start(text, 99), len(text))

    def test_paren_args_is_string_aware_and_bounded(self):
        text = 'f(a, "x) y", g(1, 2)) tail'
        self.assertEqual(source.paren_args(text, 1), 'a, "x) y", g(1, 2)')
        self.assertIsNone(source.paren_args("f(" + "a" * 30000 + ")", 1))
        self.assertIsNone(source.paren_args("f(a, b", 1))

    def test_split_args(self):
        self.assertEqual(source.split_args('a, "x, y", g(1, 2), [3, 4]'), ["a", ' "x, y"', " g(1, 2)", " [3, 4]"])


class ConstIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "packages/types/roles.ts",
              'export const ALL_ROLES: readonly UserRole[] = ["WORKER", "ADMIN"];\n'
              'export const MONEY = ["FINANCE", ...ADMIN_ONLY] as const;\n'
              'export const ADMIN_ONLY = [Role.ADMIN];\n'
              'export const LOOP_A = [...LOOP_B];\nexport const LOOP_B = [...LOOP_A];\n')
        write(self.root, "a/x.ts", "export const DUP = ['A'];\n")
        write(self.root, "b/y.ts", "export const DUP = ['B'];\n")
        self.index = source.ConstIndex(self.root)

    def test_resolves_arrays_spreads_and_enum_members(self):
        roles, _ = self.index.resolve("MONEY")
        self.assertEqual(roles, ["FINANCE", "ADMIN"])
        self.assertEqual(self.index.resolve("ALL_ROLES")[0], ["WORKER", "ADMIN"])

    def test_ambiguous_missing_and_cyclic_names_are_none(self):
        for name in ("DUP", "NOPE", "LOOP_A"):
            self.assertIsNone(self.index.resolve(name), name)

    def test_expand_handles_literals_spreads_names_and_unresolved(self):
        roles, via = self.index.expand("'ADMIN', Role.MANAGER, ...ALL_ROLES")
        self.assertEqual(roles, ["ADMIN", "MANAGER", "WORKER"])
        self.assertTrue(any("ALL_ROLES" in v for v in via))
        self.assertEqual(self.index.expand("ALL_ROLES")[0], ["WORKER", "ADMIN"])
        self.assertIsNone(self.index.expand("...NOT_DEFINED"))

    def test_local_definitions_win(self):
        local = source.scan_consts("const DUP = ['LOCAL'];\n")
        self.assertEqual(self.index.expand("DUP", local=local, local_rel="z.ts")[0], ["LOCAL"])


class PyAstTests(unittest.TestCase):
    def test_py_tree_never_raises(self):
        self.assertIsNone(pyast.py_tree("def ("))
        self.assertIsNone(pyast.py_tree("(" * 5000 + ")" * 5000))
        self.assertIsNotNone(pyast.py_tree("x = 1\n"))

    def test_index_and_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "app/dep.py",
                  "ADMIN_LIKE = (UserType.admin, UserType.developer)\n"
                  "def require_user():\n    pass\nclass Body(BaseModel):\n    name: str\n")
            idx = pyast.PyIndex(tmp)
        self.assertIn("require_user", idx.funcs)
        self.assertIn("Body", idx.classes)
        self.assertEqual(idx.consts["app/dep.py"]["ADMIN_LIKE"], ["admin", "developer"])

    def test_http_exception_info(self):
        import ast
        call = ast.parse('HTTPException(status_code=404, detail="x")').body[0].value
        status, detail = pyast.http_exception(call)
        self.assertEqual((status, detail.value), (404, "x"))
        positional = ast.parse('HTTPException(409, "y")').body[0].value
        self.assertEqual(pyast.http_exception(positional)[0], 409)
        named = ast.parse("HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='z')").body[0].value
        self.assertEqual(pyast.http_exception(named)[0], 403)
        self.assertIsNone(pyast.http_exception(ast.parse("Other(1)").body[0].value))


if __name__ == "__main__":
    unittest.main()
