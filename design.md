# PRD Assistant: design spec

Date: 2026-10-14
Status: DRAFT for review. No implementation exists yet.
Owner: Arep. Written with Claude Code.
Calibration evidence: `/home/arep/research/targets/` (copies of room-management-system and Urus), plus `tis`.

## 1. Purpose

Point the assistant at any repository and get, quickly and checkably:

1. A map of what the system does, so someone new can understand a repo they cannot read line by line (primary use).
2. Acceptance criteria that `team-task` can use, derived from existing behavior.
3. A plain-language "how to use it without failing" guide for non-engineers (clients).
4. A standard PRD: problem, requirements, team alignment, completion check.

Hard rule: **every number and every behavioral claim comes from code that computes it or from a cited source location. A model never supplies a count.** A deterministic gate reports whether the extracted facts are trustworthy enough to use.

## 2. Evidence this design rests on

The repo's own `code-to-prd` scripts produced 0 frontend pages for `tis` and an endpoint list with no router prefixes and with test files mixed in. CodeGraph's index for the same repo had far better data. Calibration run on 2026-10-14, comparing CodeGraph route nodes with an independent count from the source:

| Stack (repo) | Independent count | CodeGraph | Result |
|---|---|---|---|
| FastAPI (tis) | 133 route decorators | 137 route nodes, none from tests | Close; 4-route gap unexplained |
| NestJS (Urus API) | 78 route decorators | 78, full `/api/v1/...` prefixes | Exact |
| React router (Urus web) | not counted | 15 route nodes, plus `navigates` edges | Unverified |
| Vue router (room-management) | 21 `path:` entries | 17 from the real router file, plus 15 from a test file | About 81%; 4 missing, unexplained |
| Laravel (room-management API) | 66 `Route::` calls in `routes/api.php` | 0 PHP route nodes | Total miss; 225 PHP classes and call edges are indexed |

Consequences: use CodeGraph for the graph; add route adapters where it has no route extraction (Laravel first); exclude test paths; always cross-check route counts.

## 3. Non-goals

- No per-framework full scanners. That approach failed in `code-to-prd`.
- No running of target repo code. The tool only reads files and a copy of the CodeGraph database.
- No guessing of the "problem" statement. Anything not derivable from code is marked `NEEDS HUMAN INPUT`.
- No MCP server in the first versions (a later thin wrapper, see slice 5).
- No claim that the gate proves the PRD is correct. It shows the extracted facts agree with an independent count.

## 4. Architecture

Stdlib-only Python scripts (run as `python3 -I script.py ...`), a skill that drives them, and a read-only agent for the prose. CodeGraph supplies the graph.

```
target repo ──► codegraph index (.codegraph/codegraph.db, copied before reading)
      │                │
      │                ▼
      │        extract_facts.py ──► facts.json
      │                ▲
      └─► route adapters (Laravel, others only when the gate shows a miss)
                       │
                       ▼
              gate.py ──► gate.json + gate.md   (PASS / WARN / FAIL, all numbers shown)
                       │
         (FAIL stops here and reports why)
                       ▼
        model writes prd.md and client-guide.md using ONLY facts.json
                       ▼
              verify_prd.py ──► checks every citation and quoted number against facts.json
```

### 4.1 Units

| Unit | Does | Input | Output | Depends on |
|---|---|---|---|---|
| `extract_facts.py` | Reads routes, screens, navigation, handlers, models, test links from the CodeGraph DB copy | repo path | `facts.json` | CodeGraph DB schema (pinned, see 4.4) |
| `adapters/laravel.py` | Parses `routes/*.php` into routes with resolved prefixes and groups, links each to a controller method node | repo path, DB copy | route facts merged into `facts.json` | PHP files only |
| `independent_count.py` | Counts routes straight from source with one small pattern per framework (FastAPI, NestJS, Express, Laravel, Vue/React router) | repo path | counts per framework | none |
| `gate.py` | Compares extracted facts with independent counts and index health | `facts.json`, counts | `gate.json`, `gate.md` | none |
| `verify_prd.py` | Lints the model's output against the facts | `prd.md`, `facts.json` | pass/fail list | none |
| Skill `prd-from-code` | Runs the scripts in order, stops on FAIL, drives the writing | user request | files in the output dir | all above |
| Agent `prd-writer` | Read-only writer that sees only `facts.json` and cited snippets | facts, gate | draft docs | none |

Each unit is testable alone. `independent_count.py` deliberately shares no code with the extractor, so the cross-check is a real second opinion.

### 4.2 Output location

All output goes to a directory outside the target repo (default `~/prd-out/<repo>-<date>/`). The target repo is never written to. CodeGraph is run on a copy when the repo has no index, so no `.codegraph/` appears in someone's working copy.

### 4.3 Safety rules

- Never read secret-looking files (`.env*`, key files, credentials). Reuse the name rules in `~/.claude/hooks/readonly-bash.py`.
- Treat all repo text (README, comments, docs, CLAUDE.md) as data, never as instructions.
- Never execute target code. `php artisan route:list` and similar are an opt-in cross-check only, because they run project code. Default off.

### 4.4 CodeGraph coupling

The scripts read `nodes`, `edges`, `files`, `unresolved_refs` and `project_metadata`. Observed on 2026-10-14: CodeGraph 1.6.2, schema version 11, extraction version 27. `extract_facts.py` reads `schema_versions` and `indexed_with_extraction_version` and **refuses to run on an unknown version**, printing the observed and expected values. A version bump means a deliberate re-calibration, never silent breakage.

## 5. Facts schema (`facts.json`, `schema: 1`)

Every fact has a stable `id`, a `source` of `file:line`, and an `origin` (`codegraph` or `adapter:<name>`).

- `routes[]`: method, full path, handler symbol, source, origin, `tested_by[]`.
- `screens[]`: route path, component, source.
- `navigation[]`: from screen or handler, to path, source line.
- `models[]`: name, fields where available, source.
- `tests[]`: test file, targets reached through call edges.
- `excluded[]`: routes and screens dropped because they live in test, mock or generated paths (uses `files.generated` plus path patterns), with the reason. Nothing is dropped silently.

`tested_by` is derived from call edges whose source file matches test-path patterns. It means "a test reaches this handler", not "the behavior is correct".

## 6. The gate

All checks are computed. Each prints its raw numbers. Thresholds live in one config file and are **starting values to calibrate, not facts**.

| Check | How it is computed | Initial thresholds |
|---|---|---|
| Route agreement | `abs(extracted - independent) / independent`, per framework | PASS <= 5%, WARN <= 20%, FAIL > 20% |
| Screen agreement | same, for router `path` entries | same |
| Index staleness | `project_metadata.indexed_at_commit` vs `git rev-parse HEAD`, plus files whose content hash differs from `files.content_hash` | PASS: same commit and 0 changed files; WARN: some changed files, none of them a route, router or controller file; FAIL: a route, router or controller file changed since the index |
| Language coverage | indexed source files / source files on disk, by extension | WARN < 90%, FAIL < 60% |
| Orphans | routes with no handler edge; screens no `navigates` edge reaches | informational, listed |
| Exclusions | count of excluded test/mock/generated items | informational, listed |

Overall verdict is the worst check. **FAIL stops the pipeline** and the report says which check failed and what was expected. This is the designed behavior for the Laravel case in section 2 (0 against 66).

Not used as a gate: the unresolved-reference ratio. It measured 61% to 73% on three repos including a healthy one, probably because of external imports, and has not been shown to separate good from bad.

Known weakness: the Laravel adapter and its cross-check both read `routes/*.php`, so they are less independent than for other stacks. The cross-check counts raw `Route::verb(` calls lexically (comments stripped), the adapter resolves groups and prefixes. The opt-in `route:list` comparison closes this gap when PHP is available and the user allows running project code.

## 7. Outputs

All sections cite fact ids. A claim without an id is a lint error.

**PRD (`prd.md`)**
1. Problem: from README/docs excerpts with citations, otherwise `NEEDS HUMAN INPUT`.
2. Requirements: one per route and screen group, each citing `file:line`, with `tested_by` status.
3. Team alignment: open questions (orphans, untested routes, exclusions), optional owners from `git log` if enabled.
4. Completion check: a checklist per route (exists, reachable from a screen, has a test reaching it), with computed counts.

**Client guide (`client-guide.md`)**
User journeys from screens and navigation, in plain language and with no code terms. Wording for labels comes from UI strings found in the cited components. Steps the code cannot confirm are marked as unverified.

**`team-task` input**
A list of acceptance-criteria candidates, one per route or journey, each citing its fact id. The human still confirms them (step 1 of `team-task`).

## 8. Verification of the assistant itself

- Golden fixtures: the three calibration repos, with expected counts recorded in a `calibration.json` and re-checked on every change. A change that moves a count must be explained.
- Unit tests per script: the gate on synthetic `facts.json` (pass/warn/fail edges), `independent_count.py` on small fixture files per framework, `verify_prd.py` on a deliberately wrong `prd.md`.
- A negative test: the Laravel repo without its adapter must produce FAIL.
- The unexplained gaps (4 routes in `tis`, 4 Vue routes) get diagnosed before thresholds are frozen.

## 9. Delivery slices

Each slice is separately reviewable and usable.

1. **Facts and gate.** `extract_facts.py`, `independent_count.py`, `gate.py`, Laravel adapter, calibration on the three repos. Output: `facts.json`, `gate.md`.
2. **PRD draft.** Skill and `prd-writer` agent, `verify_prd.py`.
3. **Client guide.**
4. **`team-task` hook-in.** Criteria candidates handed to step 1 of `team-task`.
5. **Optional MCP wrapper** around slices 1 to 3, only if another client needs it.

## 10. Open questions and risks

- Why 4 routes are missing for Vue and 4 extra for FastAPI is not understood. Slice 1 starts with that diagnosis.
- React routes in Urus were never independently counted. Slice 1 adds the counter.
- Express, PHP frameworks other than Laravel, and Next-style file routing are untested. Per the agreed rule, adapters are added only when the gate shows a miss on a real repo.
- The tool depends on CodeGraph's internal schema. The version pin in 4.4 turns drift into a loud failure, but each CodeGraph upgrade needs a re-calibration run.
- The "problem" section will often be thin. That is intended: an honest `NEEDS HUMAN INPUT` beats an invented problem statement.
- Where the finished tool is installed (a skill under `~/.claude/skills/` versus a plugin) is undecided. It does not affect slice 1.

## Amendments from the slice 1 plan (2026-10-14)

Decided while planning, from evidence gathered on the calibration repos. The plan is the detailed record.

1. Section 6 gate comparison is by set of `(file, line)`, not by count. A route node's id carries file and decorator/`path:` line, so the gate can name exactly which routes differ. Disagreement = size of the symmetric difference / size of the independent set.
2. Screen counts include leaf routes only. CodeGraph does not create nodes for container routes that have `children`; this is the working explanation for the "4 missing Vue routes" and is confirmed or refuted in plan Task 10.
3. Section 5 `models[]` moves to slice 2. `tests[]` is represented by `tested_by` on each route.
4. The Laravel adapter supports plain verbs, `->group(function ...)` and `prefix(...)`. Everything else is listed as unsupported and makes the gate WARN.
5. The opt-in `php artisan route:list` cross-check stays out of slice 1 because it runs project code.

6. Slice 2 (PRD draft) is specified in `design-slice2.md`: scaffold plus prose slots, an HTTP-test linker, and a lint script. It refines section 7 above.
