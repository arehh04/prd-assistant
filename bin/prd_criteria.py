#!/usr/bin/env python3
"""Acceptance-criteria candidates from the facts of a repo, for team-task step 1.

Usage:
  python3 -I bin/prd_criteria.py lookup REPO "task words" [--max-subjects N] [--max-candidates N] [--json] [--state-dir DIR]
  python3 -I bin/prd_criteria.py build  REPO [--state-dir DIR]
  python3 -I bin/prd_criteria.py show   REPO --id C-ROLE-014 [--json] [--state-dir DIR]
Exit codes: 0 ok (including no match), 2 facts unavailable, 3 environment or input error.
The facts are cached under ~/.claude/state/prd-assistant/ and rebuilt when the repo's commit or working tree changed.
"""
import argparse
import json
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import criteria_cache, lookup  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("lookup", "build", "show"):
        p = sub.add_parser(name)
        p.add_argument("repo")
        p.add_argument("--state-dir")
        if name == "lookup":
            p.add_argument("task")
            p.add_argument("--max-subjects", type=int, default=5)
            p.add_argument("--max-candidates", type=int, default=60)
        if name != "build":
            p.add_argument("--json", action="store_true")
        if name == "show":
            p.add_argument("--id", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        cache, meta, rebuilt = criteria_cache.ensure(args.repo, args.state_dir, force=(args.command == "build"))
        bank = criteria_cache.load_bank(cache)
    except criteria_cache.FactsUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (criteria_cache.EnvError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if rebuilt:
        print("note: the facts for this repo were rebuilt", file=sys.stderr)
    info = {"repo": meta.get("repo"), "head": meta.get("head"), "built_at": meta.get("built_at"),
            "changed": meta.get("changed"), "git": meta.get("git"), "cache": str(cache)}
    if args.command == "build":
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(bank["counts"].items()))
        print(f"cache: {cache}\ncommit: {str(meta.get('head') or '?')[:7]}\ncandidates: {counts}")
        return 0
    if args.command == "show":
        c = lookup.find_candidate(bank, args.id)
        if c is None:
            print(f"error: no candidate with id {args.id!r} in this cache (ids change when the code changes)",
                  file=sys.stderr)
            return 3
        print(json.dumps({"meta": info, "candidate": c}, indent=1, ensure_ascii=False) if args.json
              else lookup.render_candidate(c, info), end="")
        return 0
    sel = lookup.select(bank, args.task, args.max_subjects, args.max_candidates)
    if args.json:
        print(json.dumps(lookup.render_json(sel, info), indent=1, ensure_ascii=False))
    else:
        print(lookup.render_markdown(sel, info, bank), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
