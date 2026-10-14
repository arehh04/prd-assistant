#!/usr/bin/env python3
"""Build a draft PRD from slice 1 facts: prepare, verify, assemble.

Usage:
  python3 -I bin/prd_draft.py prepare REPO --out DIR
  python3 -I bin/prd_draft.py verify --out DIR
  python3 -I bin/prd_draft.py assemble --out DIR
Exit codes: 0 ok, 1 lint failures, 2 gate FAIL, 3 environment or input error.
"""
import argparse
import json
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import assemble, draft  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("repo")
    p.add_argument("--out", required=True)
    for name in ("verify", "assemble"):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            summary = draft.prepare(args.repo, args.out)
            print(json.dumps(summary, indent=2, sort_keys=True))
            print(f"prepared: {args.out}/scaffold.md and slots.template.json")
            return 0
        if args.command == "verify":
            errors = draft.run_verify(args.out)
            print(json.dumps(errors, indent=2))
            return 1 if errors else 0
        target = draft.run_assemble(args.out)
        print(f"wrote {target}")
        return 0
    except draft.GateFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except draft.TamperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except assemble.AssembleError as exc:
        print(json.dumps(exc.errors, indent=2))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
