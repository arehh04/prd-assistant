# PRD Assistant, Slice 3b: Developer guide

Date: 2026-10-14
Status: DRAFT for review. No slice 3b code exists yet.
Parent specs: `design.md`, `design-slice2.md` (scaffold plus prose slots, lint, manifest), `design-slice3.md` (client guide; section 13 deferred this slice).
Process so far: decisions below were made with the user in conversation on 2026-10-14.

## 1. Purpose

Turn a repo that passed the slice 1 gate into a **developer guide**: who may call each endpoint, which request fields each endpoint accepts and with which limits, which error messages each endpoint can return, and where the frontend and the backend disagree. Readers are a developer or tester new to the project, and later slice 4, which turns the facts into acceptance-criteria candidates for `team-task`.

Output is **both**: three JSON files are the source of truth and `developer-guide.md` is built from them.

Rule inherited from slices 1 to 3: structure, counts, quotations and citations are computed by scripts; the model writes only short prose slots, which a lint checks. Anything a reader cannot read is reported as `not_read` with a reason. Nothing is guessed.

## 2. Decisions (user, 2026-10-14)

1. Audience and output: both a human document and machine-readable JSON (JSON is the source of truth).
2. Roles: backend enforcement per endpoint **and** frontend gating per screen, side by side, with mismatches flagged. A hand-written role list is a later optional input, not part of 3b.
3. Form rules: backend request rules **and** the matching frontend rules that are easy to read (HTML attributes and zod/yup schemas), joined through the existing screen-to-endpoint links, with mismatches flagged. Hand-written `if (!x) setError("...")` checks are not parsed and are listed as "not read".
4. Error messages: literal messages and templates (`User {…} not found`), attached to the endpoint whose handler contains them, plus messages in helpers the handler calls, **one call deep** (CodeGraph call edges). Deeper or table-driven messages are counted as `not_read`.
5. Approach A: three new extractors, a new command and a separate `dev/` output. Slice 1's `facts.json` and the PRD and client-guide runs are unchanged.

## 3. Evidence this design rests on (2026-10-14, calibration targets)

- Route facts (`facts.json`) already carry the handler's file and line for all three stacks, and screen-to-endpoint links exist from slice 1.
- **Urus (NestJS + React).** `@Roles(...roles)` is wrapped by named decorators (`Authenticated`, `ManagementOnly`, `OversightOnly`, `PeopleRead`, `PeopleWrite`, `FinanceRead`, `FinanceWrite`, `AdminOnly`), each expanding to a constant list from the shared package (`ADMIN_ONLY`, `OPS_MANAGE`, `ALL_ROLES`, ...). `RolesGuard` refuses a route that has neither `@Roles()` nor `@Public()`, so "undeclared" means denied. The frontend gates screens with `<RequireRole roles={rolesForPath(pathname)}>` and role groups in `apps/web/src/lib/navigation.ts`. Request validation is a zod pipe (`ZodValidationPipe`), not class-validator.
- **room-management (Laravel + Vue).** `FormRequest::rules()` returns arrays, often through helper classes (`HouseRules::required()`, `TextRules`, `PasswordPolicy::rules()` with constants `MIN`/`MAX`). `authorize()` can call `Gate::authorize('move', ...)`. `messages()` exists on some requests. Custom rules call `$fail('The :attribute ...')`. Where route middleware is declared is **not yet confirmed**; calibration must settle it.
- **tis (FastAPI + React).** `require_admin` and other `Depends(...)` guards; 218 `HTTPException(status, detail=...)` raises, many with f-strings. Request models are pydantic.
- A survey with shell `grep` was denied by the permission classifier; the evidence above comes from CodeGraph reads of the indexed copies under `/home/arep/research/targets`.

## 4. Non-goals

- No hand-written role list, no role descriptions in plain language.
- No `if (!x) setError(...)` checks, no messages more than one call deep, no table-driven message lookups.
- No stack without a reader: it is reported as `not_read`, and the run does not fail for it.
- No acceptance criteria (slice 4) and no MCP wrapper (slice 5).
- No running of the app, no tests, no network.

## 5. Pipeline

```
prd_facts.py             (slice 1)  -> facts.json, gate.json                 FAIL stops
prd_draft.py dev-prepare REPO --out OUT
    dev_roles.py         (new)      -> OUT/dev/roles.json
    dev_rules.py         (new)      -> OUT/dev/form_rules.json
    dev_errors.py        (new)      -> OUT/dev/error_messages.json
    devguide.py          (new)      -> OUT/dev/dev_gate.json, dev_gate.md, scaffold.md,
                                       slots.template.json, manifest.json, dev_summary.json
prd_draft.py verify   --out OUT/dev          (same lint as slices 2 and 3)
prd_draft.py assemble --out OUT/dev          -> OUT/dev/developer-guide.md
```

Per-stack readers live in `prd_assistant/dev/<stack>.py` behind one small interface: `read_roles(route, ctx)`, `read_request(route, ctx)`, `read_messages(route, ctx)` returning a record or `{"status": "not_read", "reason": ...}`. A reader is chosen from slice 1's detected stack and adapters. No reader for a stack or concern means `not_read` for those endpoints.

## 6. Roles (`dev_roles.py`)

Backend, per route id: `{status, roles, via, source}`.
- `status`: `read` (roles known), `public` (explicitly open), `undeclared` (no declaration; for Urus-style fail-closed guards this means denied, stated as such), `not_read` (with `reason`).
- `roles`: list of role names, or `null`.
- `via`: the chain that produced them, for example `@AdminOnly() -> ADMIN_ONLY -> [ADMIN]`. Aliases and constants are followed at most 3 hops, inside the repo only.
- Sources per stack: NestJS decorators and guards; Laravel route middleware, `authorize()` and policies/gates; FastAPI `Depends(...)` guards. Exact patterns are fixed during calibration and recorded in `docs/calibration-notes.md`.

Frontend, per screen id: `{status, roles, source}` from `RequireRole`-style components, router `meta.roles`, and role groups, resolved through the router as in slice 3.

`mismatches[]`: `{screen, endpoint, screen_roles, endpoint_roles, detail}` where a role can open a screen but the endpoint that screen calls refuses it. A mismatch needs both sides `read`; otherwise nothing is claimed.

`role_names[]`: every role name seen, for the "who can do what" table.

## 7. Form rules (`dev_rules.py`)

Backend, per route id: `{source, fields[], not_read[]}`.
- A field: `{name, required, type, min, max, pattern, one_of, raw[], source}`. `raw` keeps the original rule strings (for example `min:10`) so nothing is lost by parsing. Unknown rules stay in `raw` only.
- Laravel: `FormRequest::rules()` arrays, plus helper classes one level deep (`HouseRules::required()`), class constants (`PasswordPolicy::MIN`) resolved when they are plain literals.
- NestJS: zod schemas used by `ZodValidationPipe`, linked to the controller through the pipe's argument.
- FastAPI: pydantic model fields and `Field(...)` constraints.
- Deeper or computed rules go to `not_read` with the reason.

Frontend, per screen id: `forms[screen_id] = [{field, html_attrs, schema, source}]` from `required`/`minlength`/`maxlength`/`min`/`max`/`pattern` attributes and zod/yup schemas, joined to endpoints through slice 1's links.

`mismatches[]`: a limit that differs between form and endpoint, only when both are read and the field names match exactly.

## 8. Error messages (`dev_errors.py`)

`messages[]`: `{route, status, kind, text, via, source}`.
- `kind`: `literal` or `template`. A template replaces each interpolated value with `{…}` and keeps the fixed parts verbatim.
- `via`: `handler` (in the handler body) or `helper` (in a function the handler calls directly, found through CodeGraph call edges, one call deep).
- Status comes from the same raise or return expression (`HTTPException(404, ...)`, `NotFoundException(...)`, `abort(403, ...)`, `$fail(...)` mapped to 422). If no status can be read, it is `null`.
- Messages found in the repo but not attached to any endpoint are counted in `unattached`. Table-driven or deeper ones are counted per reason in `not_read`.

## 9. Scaffold (`devguide.py`), all computed

Sections: trust header (slice 1 verdict, three dev gate verdicts with numbers, a "not read" list); who can do what (role table and role mismatches with citations on both sides); endpoint reference (one section per endpoint group: roles, request fields with limits, error messages, each with `file:line`); forms (per screen, with mismatch flags); gaps (undeclared roles, request models not read, messages not attached). Table cells use the slice 3 escaping (`text_cell` for visible text, `cell` inside code spans).

## 10. Slots and lint

Slots: one overview and one line per endpoint group. Same lint as slices 2 and 3: one plain line, citations inside allowed evidence, digits only from allowed numbers, double-quoted strings verbatim from cited evidence, evidence is data (the instruction says so), jargon rule is not applied (this guide is for developers). Manifest hashes protect `scaffold.md` and `slots.template.json`.

## 11. The dev gate (`dev_gate.json`)

Graded like slice 3 (PASS at or above 0.90, WARN at or above 0.50, FAIL below). A check whose denominator is 0 is `INFO`, not PASS.
- `roles_coverage`: routes with status `read`, `public` or `undeclared`, over all routes.
- `rules_coverage`: routes with a request model read, over routes that take a body or query.
- `message_attachment`: messages attached to an endpoint, over all messages found.
A FAIL stops before any scaffold is written and removes older outputs (no stale files).

## 12. Errors and edge cases

- Exit codes: 0 ok, 1 lint failures, 2 gate FAIL, 3 environment or input error (including no routes).
- Missing, unreadable, oversize, secret-named or symlinked files are skipped with a count, never read. Scans are bounded so a hostile file cannot hang a run. Nothing is written into the target repo.
- Hostile text in the repo (markdown, HTML, `{{`, instructions) is data: escaped in tables and framed as data in slot instructions.
- JSON files carry `schema_version: 1`; slice 4 relies on it.

## 13. Testing (test-first)

- Fixture repos per reader, with the positive cases above and `not_read` cases (computed role lists, deeper helpers, unknown rules).
- Hostile-input tests: secret-named and symlinked files, oversize files, markdown/HTML in messages, pipes in paths, pathological strings.
- Golden calibration `expect_dev` for room-management and Urus in `calibration/calibration.json`, with a mutation check; tis documented but not pinned.
- Calibration notes record what each reader cannot read.

## 14. Risks and open questions

- Where room-management declares route middleware (not confirmed).
- How Urus's zod schemas are tied to controllers through `ZodValidationPipe` arguments, and how `@urus/types` role constants are resolved across packages.
- tis's f-string messages: template extraction must keep the fixed parts exact without evaluating code.
- Mismatch detection is only as good as the screen-to-endpoint links from slice 1; screens with no link produce no mismatch claims.
- Guard patterns outside the listed ones are `not_read`; the gate shows how much that costs per repo.

## Amendments from the slice 3b plan and calibration (2026-10-14)

1. **Screen-to-endpoint join.** `facts.json` has no such links. A screen is joined to a route when `links.link()` finds a frontend call to it in the screen's slice 3 evidence files or in files they import, up to 2 further hops (at most 300 files per screen). Typed API clients (`api.payroll.list()`) are not recognised by the slice 2 linker, so those screens are not joined; the guide's first page and `dev_summary.json` state how many screens were joined.
2. **Record fields.** Role records carry `authenticated`, `undeclared_means` (`denied`, `open` or `unknown`, per stack) and `notes`; request fields carry `messages[]`; Laravel messages from static factories carry `code`.
3. **FastAPI roles** are read from the dependency function's body with `ast`. A dependency that is found and read but contains no role or sign-in check is plumbing (an endpoint with only plumbing is `undeclared (open)` with a note); a dependency that cannot be found or depends on one that cannot be read makes the endpoint `not_read`.
4. **The dev gate's `message_attachment` check is graded `PASS`/`WARN`/`INFO` and never `FAIL`** (section 11 said FAIL below 0.50). Its denominator counts every raise site in the repo, most of which sit in services more than one call deep, a stated non-goal; a FAIL there stopped all three calibration repos although roles and rules were fine.
5. **Messages raised through static factories** (`throw ApiException::businessRule('CODE', 'message')`) are read through the factory class (status from `new self(<status>, ...)`, code and message from the call or the factory defaults).
6. **Parameters:** `@Param` maps to location `path`; FastAPI `File(...)`/`Form(...)` are body fields.
7. **Constant index** is TypeScript only; names defined in more than one file are ambiguous and resolve to `not_read`, never to a guess.
8. **Calibration answers to the open questions (section 14):** room-management declares roles as `Route::middleware('role:...')->group(...)` nested in an `auth:sanctum` group; Urus links zod through `@Body(new ZodValidationPipe(Schema))` and gates screens through a `NAV_ITEMS` table with longest-prefix match; `tis` uses `Depends(require_admin_user)`-style dependency functions.
