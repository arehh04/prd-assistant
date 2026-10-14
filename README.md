# PRD Assistant (slice 1: facts and gate)

Reads a repo's CodeGraph index, writes `facts.json`, and cross-checks it against an independent
count taken from the source. Design: `design.md`. Plan: `plans/2026-10-14-slice1-facts-and-gate.md`.

    python3 -I bin/prd_facts.py /path/to/repo --out /path/to/output

Exit code 0 = PASS or WARN, 2 = FAIL (do not build a PRD from these facts), 3 = environment or
index error. If the repo has no `.codegraph/`, a secret-free copy is indexed with `codegraph init`
and the original is never written to.

Tests: `python3 -m unittest discover -s tests -t . -v`
