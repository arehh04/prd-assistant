"""Glue: make sure an index exists, extract facts, run the gate, write the outputs."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import cgdb, count, extract, gate, report
from .adapters import laravel

SECRET_PATTERNS = (".git", "node_modules", "vendor", ".codegraph", ".env*", "*.pem", "*.key", "*.p12",
                   "*.pfx", "id_rsa*", "id_ed25519*", "credentials*", ".npmrc", ".pypirc", ".netrc")


def ensure_index(repo):
    """Return (index_root, cleanup_dir). Never writes into `repo`."""
    repo = Path(repo)
    if (repo / ".codegraph" / "codegraph.db").is_file():
        return repo, None
    work = Path(tempfile.mkdtemp(prefix="prd-index-"))
    copy = work / "copy"
    shutil.copytree(repo, copy, symlinks=True, ignore=shutil.ignore_patterns(*SECRET_PATTERNS))
    subprocess.run(["codegraph", "init", str(copy)], check=True, capture_output=True, text=True, timeout=900)
    return copy, work


def run(repo, use_adapters=True):
    repo = Path(repo).resolve()
    index_root, cleanup = ensure_index(repo)
    conn, tmp = cgdb.open_index(index_root)
    try:
        cgdb.check_versions(conn)
        frameworks = count.detect_frameworks(repo)
        facts = extract.extract_facts(conn, repo)
        if use_adapters and "laravel" in frameworks:
            routes, unsupported = laravel.load(repo)
            extract.merge_adapter_routes(conn, facts, routes, unsupported, "laravel")
        facts["meta"]["frameworks"] = sorted(frameworks)
        result = gate.run(conn, repo, facts, frameworks)
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)
    return facts, result


def write_outputs(out_dir, facts, result):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts, indent=2, sort_keys=True))
    (out / "gate.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    (out / "gate.md").write_text(report.render_gate_md(result, facts))
    (out / "summary.json").write_text(json.dumps(gate.summary(result), indent=2, sort_keys=True))
