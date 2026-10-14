"""Builders for synthetic CodeGraph indexes. Column names match CodeGraph schema 11."""
import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
create table schema_versions (version integer, applied_at integer, description text);
create table project_metadata (key text primary key, value text, updated_at integer);
create table nodes (id text primary key, kind text, name text, qualified_name text,
                    file_path text, language text, start_line integer);
create table edges (id integer primary key autoincrement, source text, target text,
                    kind text, metadata text, line integer, col integer, provenance text);
create table files (path text primary key, content_hash text, language text, size integer,
                    modified_at integer, indexed_at integer, node_count integer, errors text,
                    generated integer default 0);
"""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def node(node_id, kind, name, file_path, line, qn=None):
    return {"id": node_id, "kind": kind, "name": name, "file_path": file_path,
            "start_line": line, "qualified_name": qn}


def make_index(root, nodes=(), edges=(), files=(), meta=None, schema_version=11):
    """Write <root>/.codegraph/codegraph.db.

    edges: (source, target, kind, line, metadata_json_or_None)
    files: (path, content_hash, generated 0/1)
    """
    db_dir = Path(root) / ".codegraph"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "codegraph.db")
    conn.executescript(SCHEMA)
    conn.execute("insert into schema_versions values (?, 0, 'test')", (schema_version,))
    base = {"indexed_with_extraction_version": "27", "indexed_with_version": "1.6.2"}
    base.update(meta or {})
    for key, value in base.items():
        conn.execute("insert into project_metadata values (?, ?, 0)", (key, value))
    for n in nodes:
        conn.execute(
            "insert into nodes (id, kind, name, qualified_name, file_path, start_line) "
            "values (?, ?, ?, ?, ?, ?)",
            (n["id"], n["kind"], n["name"], n.get("qualified_name"), n["file_path"], n["start_line"]),
        )
    for source, target, kind, line, metadata in edges:
        conn.execute(
            "insert into edges (source, target, kind, metadata, line) values (?, ?, ?, ?, ?)",
            (source, target, kind, metadata, line),
        )
    for path, digest, generated in files:
        conn.execute("insert into files (path, content_hash, generated) values (?, ?, ?)",
                     (path, digest, generated))
    conn.commit()
    conn.close()
