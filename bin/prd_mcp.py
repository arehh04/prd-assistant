#!/usr/bin/env python3
"""MCP server (stdio) exposing the criteria tools: criteria_lookup, criteria_show, criteria_build, repo_status.

Usage:
  python3 -I bin/prd_mcp.py [--root DIR]... [--allow-any-repo] [--state-dir DIR]
Roots: repeatable --root, else the PRD_MCP_ROOTS environment variable (path-separated), else the working directory.
Only repos inside a root can be queried; --allow-any-repo lifts that. Facts are cached outside the repos
(--state-dir, PRD_ASSISTANT_STATE, or ~/.claude/state/prd-assistant/). stdout carries only protocol messages.
"""
import argparse
import os
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import mcp_server  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", default=[], help="a folder whose repos may be queried (repeatable)")
    parser.add_argument("--allow-any-repo", action="store_true", help="do not restrict the repos that can be queried")
    parser.add_argument("--state-dir", help="where the facts are cached")
    args = parser.parse_args(argv)
    roots, warnings = mcp_server.parse_roots(args.root, os.environ.get("PRD_MCP_ROOTS"), Path.cwd())
    for warning in warnings:
        print(warning, file=sys.stderr)
    if not roots and not args.allow_any_repo:
        print("prd-mcp: no usable root; every tool will answer with an error. Use --root DIR or PRD_MCP_ROOTS.", file=sys.stderr)
    config = mcp_server.Config(roots, args.allow_any_repo, args.state_dir)
    return mcp_server.serve(sys.stdin.buffer, sys.stdout.buffer, config)


if __name__ == "__main__":
    sys.exit(main())
