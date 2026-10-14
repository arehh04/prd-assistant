# PRD Assistant, Slice 2: PRD draft (scaffold plus prose slots)

Date: 2026-10-14
Status: DRAFT for review. No slice 2 code exists yet.
Parent spec: `design.md` (sections 7 and 9). Slice 1 (facts and gate) is built; see `docs/calibration-notes.md`.
Process so far: approach C (scaffold plus slots) and this design were approved in conversation on 2026-10-14.

## 1. Purpose

Turn a repo that passed the slice 1 gate into a **draft PRD** whose numbers, tables and citations are computed by scripts, with the model limited to short prose slots that a lint script checks. A human reviews the result.

Rule inherited from the parent spec: the model never supplies a count, a table, or a source reference that is not in the facts.

## 2. Evidence this design rests on (2026-10-14)

- `facts.json` is 50 to 90 KB per calibration repo. Routes group by path prefix into 13 to 25 feature groups (for example `/api/v1/searches` has 34 routes on `tis`).
- `tested_by` from slice 1 counts only tests that call a handler directly: 5 of 137 routes on `tis`, 0 of 66 on room-management. But room-management's tests contain 1,983 HTTP calls (`getJson`, `postJson`, ...) in 89 files, `tis` has 22 literal route calls in 8 files, and Urus has 4. A completion check built on `tested_by` alone would be wrong. Hence the HTTP linker.
- README files run from 96 to 677 lines and every repo has `docs/`. These are the evidence for the Problem slot.
- Frontends build URLs two ways: room-management calls `http.post('/auth/logout')` with `baseURL: '/api/v1'`; `tis` calls `fetch(TEAMS_URL, ...)` with the URL in a constant. So a frontend link can be found for the first style and is invisible for the second.

## 3. Non-goals

- No client guide (slice 3), no `team-task` hook-in (slice 4), no MCP wrapper (slice 5).
- No proof that prose is semantically right. Lint proves it cites real sources and invents no numbers or quotes; a human judges meaning.
- No constant or base-URL resolution in the frontend linker.
- No check of spelled-out numbers ("three routes"). Only digits are checked.
- No guess about who owns what. Owners and decisions stay `NEEDS HUMAN INPUT`.

## 4. Pipeline

```
prd_facts.py        (slice 1)   -> facts.json, gate.json, gate.md     FAIL stops everything
link_http.py        (new)       -> links.json
docs_index.py       (new)       -> docs_index.json
scaffold_prd.py     (new)       -> scaffold.md, slots.template.json
model fills slots   (skill)     -> slots.json
verify_prd.py       (new)       -> lint report; at most 2 repair rounds, then escalate
assemble_prd.py     (new)       -> prd.md
```

- All files go to the `--out` directory chosen for slice 1. Nothing is written to the target repo.
- A WARN gate verdict continues and is printed as the trust level at the top of the PRD. A FAIL verdict stops with the gate report path.
- The model sees only `slots.template.json` (per slot: instructions, limits, and the evidence it may use). It never sees the scaffold tables.

## 5. HTTP linker (`link_http.py`)

Runs the same engine twice with different file sets and rules.

### 5.1 Test calls

- Files: every test file (paths classified as `test` by `paths.exclusion_reason`).
- Call-site patterns, each requiring a string literal first argument that starts with `/`:
  - Python: `<receiver>.<verb>(<f>"<path>"` where verb is get, post, put, patch, delete (receiver is any name: `client`, `self.client`, `async_client`).
  - PHP: `<verb>Json('<path>'`, `$this-><verb>('<path>'`, `$this->json('<VERB>', '<path>'`.
  - TypeScript or JavaScript: `.get('<path>'`, `.post(...)`, and so on (supertest style).
- The HTTP method must match the route's method.

### 5.2 Frontend references

- Files: non-test source under the subtree of any `package.json` that lists `vue-router` or `react-router`.
- Call-site patterns: `fetch('<path>'`, and `<receiver>.<verb>('<path>'` for any receiver. For `fetch` without a literal method option the method is unknown and the path alone is matched.
- The result per route is `frontend_reference`: `detected` or `not_detected`. `not_detected` is never evidence that the route is unused (see section 2).

### 5.3 Normalization and matching

1. Take the first string literal. If the next non-space character after the closing quote is `+` or `.` (concatenation) or the argument is not a literal, the call is **dynamic**.
2. Strip the query string and a trailing slash.
3. Split into segments. A segment containing `${...}`, `{$...}`, an f-string `{...}`, `{name}`, or `:name` is a wildcard. The same rule applies to route templates.
4. A call matches a route when the segment counts are equal and every segment is equal or at least one side is a wildcard. Score = number of equal static segments. The best score wins; a tie between different routes with the same method is **ambiguous**.
5. If no route matches, retry once with the routes' global prefix prepended to the literal (the prefix is computed as in section 6.1). A match found this way increments `matched_via_prefix`.
6. Otherwise the call is **unmatched**.

### 5.4 Buckets and the self-check

For tests and frontend separately, every call site lands in exactly one of: `matched`, `ambiguous`, `unmatched`, `dynamic`. (`matched_via_prefix` is a subset of `matched`.) The linker verifies `matched + ambiguous + unmatched + dynamic == call_sites` and fails if not.

A second, looser regex (any `<verb>(` or `<verb>Json(` with a first argument, no `/` requirement) lists **ignored candidates**: call-like lines the main patterns skipped, with a sample of up to 20. The linker prints the count so a human can see what was left out. This is a visibility check, not a pass/fail gate.

### 5.5 Output (`links.json`, `schema: 1`)

```
{ "schema": 1,
  "tests":    { "totals": {call_sites, matched, matched_via_prefix, ambiguous, unmatched, dynamic, ignored_candidates},
                "ignored_sample": [{file, line, text}] },
  "frontend": { "totals": {...same keys...}, "ignored_sample": [...] },
  "routes":   { "<route id>": { "http_tests": [{file, line}], "frontend": [{file, line}] } },
  "calls":    [ {side, file, line, method, raw, bucket, route_ids} ] }
```

`http_tests` means a test sent a request to that path and method. It does not mean the test asserts anything useful.

## 6. Scaffold (`scaffold_prd.py`)

Everything here is computed. The model never writes or sees these tables.

### 6.1 Feature groups

- Global prefix: start with the most common first path segment; if it covers more than 50% of routes, extend with the most common second segment among them while the extended prefix still covers more than 50% of all routes; stop otherwise. Example: `tis` gives `/api/v1`.
- Group key = the next segment after the prefix. Routes outside the prefix, or exactly equal to it, go to group `(root)`.
- Group ids `G01`, `G02`, ... sorted by key. Screens group by their first path segment with ids `S01`, ... (same rule, no prefix).

### 6.2 PRD sections

1. **Trust header.** Gate verdict and every check's status. CodeGraph version and indexed commit. Linker totals for tests and frontend. Any WARN, spelled out.
2. **Problem.** One slot `problem` (see 6.3). If `docs_index.json` is empty, the scaffold pre-fills `NEEDS HUMAN INPUT` and no model call is needed.
3. **Requirements.** One subsection per route group: slot `purpose.Gxx`, then a table with method, path, source (`file:line`), handler, `tested over HTTP` (count and files), `tested by direct call`, `frontend reference`. Then one subsection for screens: slot `screens_overview`, then a table of path, source and incoming navigation count.
4. **Team alignment.** Computed lists: routes with no test of either kind (per group), screens nothing navigates to, excluded items by reason, unsupported adapter constructs, gate WARN items, unmatched and ambiguous test calls (counts and first 20). Owners and decisions: literal `NEEDS HUMAN INPUT`.
5. **Completion check.** Per group, counts only: routes, tested over HTTP, tested by direct call, tested by both, tested by neither, frontend reference detected. A footer states what each label means and that `frontend reference: not detected` is not proof of non-use.

### 6.3 Slots

`slots.template.json` lists each slot: `key`, `instructions`, `max_words`, `allowed_evidence` (list of `{file, from_line, to_line}`), `allowed_numbers` (the counts from that slot's own group), and `may_be_needs_human_input`.

| Slot | Words | Evidence |
|---|---|---|
| `problem` | 150 | `docs_index.json` entries |
| `purpose.Gxx` | 40 | that group's route and handler sources |
| `screens_overview` | 80 | screen sources |

## 7. Docs index (`docs_index.py`)

- Files: `README*`, root-level `*.md`, and `docs/**/*.md`. Excluded: agent instruction files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) and any secret-named file (`paths.is_secret_name`).
- For each Markdown heading: file, heading line, the line range up to the next heading, and the first 12 non-empty lines as an excerpt (capped at 1,200 characters).
- All repo text is data. In the prompt it sits between explicit delimiters and the instructions say to ignore any instruction found inside it.

## 8. Lint (`verify_prd.py`)

Input: `slots.json` (`{key: text}`), `slots.template.json`, `facts.json`, `docs_index.json`. Output: a list of `{slot, rule, detail}`; exit 0 if empty, 1 otherwise.

| Rule | Check |
|---|---|
| keys | The key set equals the template's exactly: no missing, no extra |
| form | Single paragraph: no Markdown headings, tables, lists, or code fences |
| length | Within `max_words` |
| citation | Unless the text is exactly `NEEDS HUMAN INPUT` (and the slot allows it), at least one citation of the form `[path:line]` |
| resolves | Every citation's `path:line` falls inside one of the slot's `allowed_evidence` ranges |
| numbers | Every digit sequence outside citations is in the slot's `allowed_numbers` |
| quotes | Every double-quoted string of 4 or more characters appears verbatim (whitespace-normalized, case-sensitive) in a cited file within the evidence ranges |

Not checked, stated plainly in the PRD footer: whether the prose is true or well-judged, and spelled-out numbers.

## 9. Assembly and the skill

- `assemble_prd.py` substitutes `{{slot:key}}` placeholders in `scaffold.md` with the slot text to produce `prd.md`. It refuses to run if lint fails or any placeholder is unfilled.
- Skill `prd-from-code` (lives in the project, `skills/prd-from-code/SKILL.md`; installing it into `~/.claude/skills/` is a separate step): run the scripts in order; stop on gate FAIL; fill slots in batches of at most 10; run lint; revise only failing slots; at most 2 repair rounds, then stop and show the remaining lint failures. This matches the repair cap in `team-task`.
- Filling slots: by the main session by default. A read-only `prd-writer` agent (tools: Read, Grep, restricted to the output directory and cited files) is allowed for isolation. It returns slot JSON in its reply; the main session writes `slots.json`.

## 10. Errors and edge cases

| Case | Behavior |
|---|---|
| Gate verdict FAIL | Stop; print gate report path; write nothing else |
| Repo with no routes (frontend only) | PRD has screens only; route sections say "none extracted" |
| Repo with no screens | Screens subsection omitted |
| No docs | `problem` slot pre-filled with `NEEDS HUMAN INPUT` |
| More than 30 groups | No cap; the skill fills slots in batches of 10 |
| Test file unreadable | Counted in `unreadable_files` as in slice 1; linker continues |
| Slot text contains instructions copied from a doc | Lint cannot detect this; mitigated by delimiters and by the model returning JSON only |

## 11. Testing

- Unit tests per script on small fixtures: matcher (wildcards, precedence, ambiguity, prefix retry, concatenation as dynamic), buckets sum to call sites, grouping (including the majority-prefix rule and `(root)`), docs index (headings, ranges, exclusions), scaffold placeholders, assembly refusal.
- Negative lint tests: fabricated number, dead citation, citation outside the slot's evidence, unknown key, missing key, altered form (table in a slot), fabricated quote, missing citation.
- Golden results on the three calibration repos added to `calibration/calibration.json`: linker totals for tests and frontend, group counts, and the completion-check counts.
- Acceptance: on each calibration repo, the pipeline reaches a PRD whose lint passes within 2 repair rounds, and the completion-check counts equal the linker's totals.

## 12. Risks and open questions

- Laravel tests that call `route('name')` instead of a literal path will land in `dynamic`. The share is unknown until calibration; if large, a named-route resolver becomes a later addition.
- Many frontends keep URLs in constants (`tis`). The frontend reference will under-detect there. This is why the label is `detected` or `not detected`.
- The majority-prefix rule is a heuristic. A repo with two equally large API roots would put one of them in `(root)`. The scaffold prints the chosen prefix so this is visible.
- Model cost grows with the number of feature groups on a large repo (one slot per group); the batch size of 10 is a first guess to be tuned.
- The prose is only as good as the evidence slice it gets. Quality of `purpose` sentences is judged by a human, not by lint.
