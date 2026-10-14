import shutil
import tempfile
import unittest
from pathlib import Path

from prd_assistant import cgdb
from tests.helpers import make_index, node


class CgdbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_open_index_reads_a_private_copy(self):
        make_index(self.root, nodes=[node("n1", "function", "f", "a.py", 1)])
        db = self.root / ".codegraph" / "codegraph.db"
        before = db.read_bytes()
        conn, tmp = cgdb.open_index(self.root)
        try:
            self.assertEqual(conn.execute("select count(*) from nodes").fetchone()[0], 1)
            conn.execute("delete from nodes")
            conn.commit()
        finally:
            conn.close()
            shutil.rmtree(tmp)
        self.assertEqual(db.read_bytes(), before)

    def test_missing_index_raises(self):
        with self.assertRaises(FileNotFoundError):
            cgdb.open_index(self.root)

    def test_supported_versions_pass(self):
        make_index(self.root)
        conn, tmp = cgdb.open_index(self.root)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(conn.close)
        cgdb.check_versions(conn)  # must not raise
        self.assertEqual(cgdb.get_meta(conn, "indexed_with_version"), "1.6.2")
        self.assertIsNone(cgdb.get_meta(conn, "no_such_key"))

    def test_unknown_schema_version_is_refused_with_a_clear_message(self):
        make_index(self.root, schema_version=10)
        conn, tmp = cgdb.open_index(self.root)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(conn.close)
        with self.assertRaises(cgdb.VersionError) as ctx:
            cgdb.check_versions(conn)
        self.assertIn("schema=10", str(ctx.exception))
        self.assertIn("expected 11", str(ctx.exception))

    def test_unknown_extraction_version_is_refused(self):
        make_index(self.root, meta={"indexed_with_extraction_version": "99"})
        conn, tmp = cgdb.open_index(self.root)
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(conn.close)
        with self.assertRaises(cgdb.VersionError) as ctx:
            cgdb.check_versions(conn)
        self.assertIn("extraction=99", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
