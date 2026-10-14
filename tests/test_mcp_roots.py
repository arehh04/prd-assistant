import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import mcp_server as m


class ParseRootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a, self.b, self.c = (Path(self.tmp.name).resolve() / n for n in "abc")
        for d in (self.a, self.b, self.c):
            d.mkdir()

    def test_cli_roots_win_over_env_and_cwd(self):
        roots, warnings = m.parse_roots([str(self.a), str(self.b)], str(self.c), self.c)
        self.assertEqual((roots, warnings), ([self.a, self.b], []))

    def test_env_is_used_when_there_is_no_cli_root_and_cwd_when_there_is_neither(self):
        roots, _ = m.parse_roots([], os.pathsep.join([str(self.a), str(self.b)]), self.c)
        self.assertEqual(roots, [self.a, self.b])
        self.assertEqual(m.parse_roots([], None, self.c)[0], [self.c])
        self.assertEqual(m.parse_roots(None, "  ", self.c)[0], [self.c])

    def test_missing_and_file_roots_are_ignored_with_a_warning(self):
        f = self.a / "file.txt"
        f.write_text("x")
        roots, warnings = m.parse_roots([str(self.a), str(self.tmp.name) + "/nope", str(f)], None, self.c)
        self.assertEqual(roots, [self.a])
        self.assertEqual(len(warnings), 2)

    def test_a_working_directory_that_is_the_filesystem_root_is_never_a_default_root(self):
        roots, warnings = m.parse_roots([], None, Path("/"))
        self.assertEqual(roots, [])
        self.assertTrue(any("working directory" in w for w in warnings))
        self.assertEqual(m.parse_roots(["/"], None, self.c)[0], [Path("/")])    # an explicit choice is respected

    def test_roots_are_resolved_and_deduplicated(self):
        link = Path(self.tmp.name) / "link"
        os.symlink(self.a, link)
        self.assertEqual(m.parse_roots([str(link), str(self.a)], None, self.c)[0], [self.a])


class ResolveRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root, self.evil, self.outside = base / "root", base / "root-evil", base / "outside"
        for d in (self.root / "repo", self.evil / "repo", self.outside / "repo"):
            d.mkdir(parents=True)
        os.symlink(self.outside, self.root / "link")
        self.config = m.Config(roots=[self.root])

    def resolve(self, arg, config=None):
        return m.resolve_repo(str(arg), config or self.config)

    def test_inside_the_root_and_the_root_itself(self):
        self.assertEqual(self.resolve(self.root / "repo"), self.root / "repo")
        self.assertEqual(self.resolve(self.root), self.root)

    def test_escapes_are_rejected(self):
        for arg in (self.outside / "repo", self.evil / "repo", self.evil, self.root / "link" / "repo",
                    self.root / ".." / "outside" / "repo", self.root / "repo" / ".." / ".." / "outside"):
            with self.assertRaises(m.RepoError, msg=str(arg)):
                self.resolve(arg)

    def test_relative_paths_resolve_against_the_working_directory_then_are_checked(self):
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        self.assertEqual(self.resolve("repo"), self.root / "repo")
        os.chdir(self.outside)
        with self.assertRaises(m.RepoError):
            self.resolve("repo")

    def test_tilde_is_expanded_before_the_check(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.root)}):
            self.assertEqual(self.resolve("~/repo"), self.root / "repo")
        with mock.patch.dict(os.environ, {"HOME": str(self.outside)}):
            with self.assertRaises(m.RepoError):
                self.resolve("~/repo")

    def test_bad_values(self):
        for arg in ("repo\x00evil", str(self.root / "missing"), str(self.root / "repo" / "nope")):
            with self.assertRaises(m.RepoError):
                self.resolve(arg)
        f = self.root / "file.txt"
        f.write_text("x")
        with self.assertRaises(m.RepoError):
            self.resolve(f)

    def test_allow_any_repo_still_requires_a_directory(self):
        config = m.Config(roots=[], allow_any=True)
        self.assertEqual(self.resolve(self.outside / "repo", config), self.outside / "repo")
        with self.assertRaises(m.RepoError):
            self.resolve(self.outside / "nope", config)

    def test_no_roots_rejects_everything_and_the_message_says_how_to_fix_it(self):
        with self.assertRaises(m.RepoError) as ctx:
            self.resolve(self.root / "repo", m.Config(roots=[]))
        for needle in ("--root", "PRD_MCP_ROOTS", "--allow-any-repo"):
            self.assertIn(needle, str(ctx.exception))

    def test_the_message_escapes_and_clips_what_the_caller_typed(self):
        hostile = "<img src=x> {{slot:a}} " + "z" * 5000
        with self.assertRaises(m.RepoError) as ctx:
            self.resolve(hostile)
        text = str(ctx.exception)
        self.assertNotIn("<img", text.replace("\\<", ""))
        self.assertNotIn("{{slot:", text)
        self.assertLess(len(text), 1200)

    def test_the_resolved_path_is_what_is_returned(self):
        resolved = self.resolve(self.root / "repo")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, resolved.resolve())


if __name__ == "__main__":
    unittest.main()
