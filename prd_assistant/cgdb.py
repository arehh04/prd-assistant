"""Read-only access to a CodeGraph index. Always works on a private copy of the database."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

EXPECTED_SCHEMA = 11
EXPECTED_EXTRACTION = "27"


class VersionError(RuntimeError):
    """The CodeGraph index was built by a version this tool was not calibrated against."""


def open_index(repo_root):
    """Copy <repo_root>/.codegraph/codegraph.db (and -wal/-shm) to a temp dir and open the copy.

    Returns (connection, temp_dir). The caller closes the connection and deletes temp_dir.
    """
    src = Path(repo_root) / ".codegraph" / "codegraph.db"
    if not src.is_file():
        raise FileNotFoundError(f"no CodeGraph index at {src}")
    tmp = Path(tempfile.mkdtemp(prefix="prd-assistant-"))
    for suffix in ("", "-wal", "-shm"):
        part = Path(str(src) + suffix)
        if part.is_file():
            shutil.copy2(part, tmp / ("codegraph.db" + suffix))
    conn = sqlite3.connect(tmp / "codegraph.db")
    conn.row_factory = sqlite3.Row
    return conn, tmp


def get_meta(conn, key):
    row = conn.execute("select value from project_metadata where key = ?", (key,)).fetchone()
    return row["value"] if row else None


def check_versions(conn):
    try:
        schema = conn.execute("select max(version) from schema_versions").fetchone()[0]
        extraction = get_meta(conn, "indexed_with_extraction_version")
    except sqlite3.Error as exc:
        raise VersionError(f"unreadable CodeGraph index ({exc}); rebuild it with `codegraph index`") from exc
    if schema != EXPECTED_SCHEMA or extraction != EXPECTED_EXTRACTION:
        raise VersionError(
            f"unsupported CodeGraph index: schema={schema} (expected {EXPECTED_SCHEMA}), "
            f"extraction={extraction} (expected {EXPECTED_EXTRACTION}). "
            "Re-run the calibration before trusting this version."
        )
