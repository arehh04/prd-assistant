"""Regression tests for the final whole-branch review (Important findings 1-5)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import cgdb, count, paths, pipeline
from tests.helpers import make_index
from tests.test_pipeline import build_repo

CLI = Path(__file__).resolve().parent.parent / "bin" / "prd_facts.py"


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class SecretFilesAreNeverReadTests(unittest.TestCase):
    def test_secret_name_rules(self):
        for name in (".env", ".env.local", "credentials.json", "serviceAccountKey.json",
                     "service-account-prod.json", "secrets.json", "app_secret.yml", "server.pem",
                     "private.key", "id_rsa", ".npmrc"):
            self.assertTrue(paths.is_secret_name(name), name)
        for name in ("package.json", "SecretsController.php", "Testimonials.tsx", "composer.json",
                     "requirements.txt", "keyboard.ts"):
            self.assertFalse(paths.is_secret_name(name), name)

    def test_detect_frameworks_reads_only_manifest_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "package.json", '{"dependencies": {"@nestjs/core": "1"}}')
            write(tmp, "config/credentials.json", '{"token": "abc"}')
            write(tmp, "config/serviceAccountKey.json", '{"private_key": "abc"}')
            write(tmp, "data/huge-export.json", '{"rows": []}')
            write(tmp, "notes.txt", "hello")
            seen = []
            real = count.read_text

            def spy(path):
                seen.append(Path(path).name)
                return real(path)

            with mock.patch("prd_assistant.count.read_text", side_effect=spy):
                found = count.detect_frameworks(tmp)
        self.assertEqual(found, {"nestjs"})
        self.assertEqual(seen, ["package.json"])


class CorruptIndexTests(unittest.TestCase):
    def _repo_with_db_bytes(self, tmp, data):
        repo = Path(tmp) / "repo"
        (repo / ".codegraph").mkdir(parents=True)
        (repo / ".codegraph" / "codegraph.db").write_bytes(data)
        return repo

    def test_garbage_and_empty_databases_raise_version_error(self):
        for label, data in (("garbage", b"this is not a database" * 10), ("empty", b"")):
            with self.subTest(db=label), tempfile.TemporaryDirectory() as tmp:
                repo = self._repo_with_db_bytes(tmp, data)
                conn, tmpdir = cgdb.open_index(repo)
                self.addCleanup(shutil.rmtree, tmpdir)
                self.addCleanup(conn.close)
                with self.assertRaises(cgdb.VersionError) as ctx:
                    cgdb.check_versions(conn)
                self.assertIn("unreadable CodeGraph index", str(ctx.exception))

    def test_cli_exits_three_on_a_corrupt_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo_with_db_bytes(tmp, b"garbage" * 50)
            done = subprocess.run([sys.executable, "-I", str(CLI), str(repo), "--out", str(Path(tmp) / "out")],
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertNotIn("Traceback", done.stderr)


class UnreadableFilesTests(unittest.TestCase):
    def setUp(self):
        count.reset_unreadable()

    def test_broken_symlink_does_not_abort_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp)
            (Path(tmp) / "routes").mkdir()
            os.symlink("nowhere", Path(tmp) / "routes" / "x.php")
            _, result = pipeline.run(tmp)
        self.assertIn(result["verdict"], ("PASS", "WARN", "FAIL"))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
    def test_permission_denied_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp)
            locked = write(tmp, "app/locked.py", "@router.get('/x')\n")
            locked.chmod(0o000)
            try:
                _, result = pipeline.run(tmp)
            finally:
                locked.chmod(0o644)
        check = next(c for c in result["checks"] if c["name"] == "unreadable_files")
        self.assertEqual(check["status"], "WARN")
        self.assertTrue(any(item.endswith("locked.py") for item in check["detail"]["items"]))
        self.assertEqual(result["verdict"] in ("WARN", "FAIL"), True)


class NewRouteFileAfterIndexTests(unittest.TestCase):
    def test_route_file_added_after_indexing_fails_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp)
            write(tmp, "routes/web.php", "<?php\nRoute::get('/new', X::class);\n")
            _, result = pipeline.run(tmp)
        check = next(c for c in result["checks"] if c["name"] == "index_staleness")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("routes/web.php", check["detail"]["relevant_changed"])
        self.assertEqual(result["verdict"], "FAIL")

    def test_unindexed_non_route_file_is_left_to_the_coverage_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp)
            write(tmp, "lib/helpers.py", "x = 1\n")
            _, result = pipeline.run(tmp)
        check = next(c for c in result["checks"] if c["name"] == "index_staleness")
        self.assertEqual(check["status"], "PASS")


class IndexCopyCleanupTests(unittest.TestCase):
    def test_failed_codegraph_init_does_not_leak_the_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, "app/api.py", "x = 1\n")
            work = Path(tmp) / "work"
            work.mkdir()
            boom = subprocess.CalledProcessError(1, ["codegraph", "init"])
            with mock.patch("prd_assistant.pipeline.tempfile.mkdtemp", return_value=str(work)), \
                    mock.patch("prd_assistant.pipeline.subprocess.run", side_effect=boom):
                with self.assertRaises(subprocess.CalledProcessError):
                    pipeline.ensure_index(repo)
            self.assertFalse(work.exists())


if __name__ == "__main__":
    unittest.main()
