#!/usr/bin/env python3
"""Extract routes/screens from a repo's CodeGraph index and run the trust gate.

Usage: python3 -I bin/prd_facts.py REPO [--out DIR] [--no-adapters]
Exit codes: 0 PASS/WARN, 2 FAIL, 3 environment or index error.
"""
import argparse
import datetime
import subprocess
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import cgdb, pipeline  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo")
    parser.add_argument("--out", help="output directory (default ~/prd-out/<repo>-<date>)")
    parser.add_argument("--no-adapters", action="store_true", help="do not use route adapters (Laravel)")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 3
    out = Path(args.out) if args.out else (
        Path.home() / "prd-out" / f"{repo.resolve().name}-{datetime.date.today().isoformat()}")
    try:
        facts, result = pipeline.run(repo, use_adapters=not args.no_adapters)
    except (cgdb.VersionError, FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    pipeline.write_outputs(out, facts, result)
    for check in result["checks"]:
        print(f"{check['status']:5} {check['name']}")
    print(f"verdict: {result['verdict']}  (output: {out})")
    return 2 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
