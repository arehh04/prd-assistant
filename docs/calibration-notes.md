# Calibration notes (slice 1), 2026-10-14

Command for each block: `python3 -I bin/prd_facts.py <repo> --out ~/research/prd-out/<name> [--no-adapters]`.
CodeGraph 1.6.2, schema 11, extraction 27. Numbers are from each run's `summary.json`.

## room-management-system (Laravel API + Vue SPA), with adapter: WARN

| | extracted | independent |
|---|---|---|
| routes | 66 | 66 |
| screens | 17 | 18 |

- Routes: exact agreement, all 66 handlers resolved to PHP controller method nodes (0 routes without a handler). Caveat: the Laravel adapter and its cross-check both read `routes/api.php` (design section 6), so this agreement is weaker evidence than the NestJS one.
- Screens, missing in CodeGraph: `frontend/src/router/index.ts:27`. That is the root route `{ path: '', name: 'root', ... component: { render: () => null } }` under the public layout. CodeGraph creates no route node for it (it has no imported component). Decision: accept and document. It is a route the app never renders ("the guard always redirects"), so WARN at 5.6% is the honest result.
- Earlier "4 missing Vue routes" explained: 3 were layout routes with `children` (`/`, `/admin`, `/portal`), now skipped by the leaf-only counter, plus the 1 above. The planning hypothesis was right.
- Exclusions: 35 = 18 test-file routes (`frontend/src/__tests__/mount.ts`) + 17 navigation edges whose target is one of those test routes.
- Finding (not fixed in slice 1): CodeGraph resolves `navigates` edges to the test-file route nodes, so all 17 navigation facts are dropped as `target-excluded`, and "screens nothing navigates to: 17" is misleading for this repo. Matters for slice 3 (client guide). Likely fix: when a navigation target is excluded, fall back to the non-excluded screen with the same path.

## room-management-system, adapter disabled: FAIL (expected)

routes 0 extracted against 66 independent. This is the negative test from the design: without the adapter the gate must refuse Laravel routes. Confirmed.

## Urus (NestJS API + React SPA): PASS

| | extracted | independent |
|---|---|---|
| routes | 78 | 78 |
| screens | 15 | 15 |

Exact agreement on both. No exclusions. 2 screens have no incoming navigation.

## tis (FastAPI + React): PASS (not a golden test, the working tree changes daily)

| | extracted | independent |
|---|---|---|
| routes | 137 | 137 |
| screens | 21 | 21 |

- The earlier "133 vs 137" gap was my first grep being too narrow (it anchored on `^@(router|app)` and a different path filter). The tool's independent counter, which accepts any `@<name>.<verb>(` decorator including the `@app.get` routes in `backend/api/app.py`, agrees exactly with CodeGraph.
- 10 screens have no incoming navigation (informational).

## Thresholds

The starting values (PASS <= 5%, WARN <= 20%) behaved sensibly: exact matches PASS, the single unrendered root route WARNs, and the total miss FAILs. Three repos is too few to freeze them; revisit when a fourth stack is calibrated.

## Slice 2 (PRD draft), 2026-10-14

Commands: `python3 -I bin/prd_facts.py <repo> --out ~/research/prd-out2/<name>` then `python3 -I bin/prd_draft.py prepare <repo> --out ~/research/prd-out2/<name>`.
Numbers below are from each run's `draft_summary.json` after the two linker fixes described under "Defects".

| | route groups | screen groups | test calls (matched / ambiguous / unmatched / dynamic) | ignored candidates | frontend calls (matched / ambiguous / unmatched / dynamic) |
|---|---|---|---|---|---|
| room-management (Laravel + Vue) | 13 | 6 | 1,996 (1,671 / 12 / 17 / 296) | 149 | 4 (3 / 0 / 1 / 0) |
| Urus (NestJS + React) | 14 | 11 | 4 (0 / 0 / 4 / 0) | 8 | 1 (1 / 0 / 0 / 0) |
| tis (FastAPI + React), not golden | 12 | 12 | 22 (22 / 0 / 0 / 0) | 273 | 109 (67 / 3 / 2 / 37) |

Prefix chosen on all three: `/api/v1`.

### Completion check totals

- room-management: 66 routes, 66 HTTP-tested, 0 direct-tested, frontend reference detected 3.
- Urus: 78 routes, 0 HTTP-tested, 11 direct-tested, 67 tested by neither, frontend reference detected 1.
- tis: 137 routes, 5 HTTP-tested, 5 direct-tested, 0 both, 127 neither, frontend reference detected 68.

The slice 1 `tested_by` alone would have said "0 of 66 tested" for room-management. The linker corrects that to 66 of 66.

### Defects found by calibration and fixed (both test-first)

1. **Leading base-URL interpolation.** `tis` writes `` `${API_BASE_URL}/api/v1/auth/login` `` and `` `${USERS_URL}/${userId}` ``. The matcher treated the leading `${...}` as an ordinary one-segment wildcard, so true matches were missed (4 auth calls and the Urus chat stream came out unmatched) and an all-wildcard call matched every group (14 spurious "ambiguous" in tis). Fix: an all-wildcard call is `dynamic`; a match needs at least one equal static segment (the root path is exempt); a leading wildcard matches the END of a route. After the fix tis frontend went from 57 matched / 14 ambiguous / 13 unmatched / 25 dynamic to 67 / 3 / 2 / 37.
2. **Frontend unit tests counted as backend tests.** `frontend/src/**/*.spec.ts` in room-management call a mocked `http.get('/houses')`; the prefix retry matched them to `GET /api/v1/houses`. Fix: test files inside a non-root frontend package are excluded from the test side.

### Hand checks

- tis `POST /api/v1/teams`: table says 2 calls in 1 file; grep for the literal call finds 2.
- room-management `GET /api/v1/houses`: table says 18 calls in 6 files; independent grep finds 19. The single difference is `BoardAndListsTest.php:259`, where the path is built as `'/api/v1/houses?...&q='.rawurlencode($q)`; concatenated paths are classified `dynamic` on purpose. All 18 credited calls are genuine.

### Reading the buckets

- room-management unmatched (17): legitimate. Adversarial tests call routes that do not exist (`/api/v1/_test/*`, `/api/v1/does-not-exist`, `POST /api/v1/branches/{x}`) and Laravel Sanctum's built-in `/sanctum/csrf-cookie`.
- room-management ambiguous (12): calls whose path contains a variable endpoint name such as `/api/v1/auth/{$endpoint}`. They cannot be resolved and are correctly not credited to any route.
- Urus tests (4, all unmatched): these are in `packages/api-client/src/client.spec.ts` and call `/api/test` on a client under test. Urus effectively has no HTTP-level API tests, so its completion check shows 67 of 78 routes with no test of either kind.

### Known limitations (documented, not fixed)

- **tis test calls are under-counted.** The ignored sample shows real calls the linker skips on purpose: `_client(user_type).get(BASE + path)` and `.get(f"{BASE}/details?metric={metric}")`. A call whose first argument is not a literal starting with `/` is only counted when the call name is unambiguous (`getJson`, `fetch`). Idea for a later slice: treat `.get(` on a receiver named like a test client as a `dynamic` call, and treat an f-string that starts with an interpolation like the leading-base-URL case.
- Frontend wrappers (`connectorsApi.delete(id)`) and templates that start with a function call (`` `${tenantPath(id)}/portal-access` ``) are invisible to the frontend linker. So `frontend reference: not detected` stays weak evidence, as the PRD footer says.
- `fetch(TEAMS_URL)` with the URL in a constant is counted `dynamic`.

### The full loop on Urus (acceptance run)

Followed `skills/prd-from-code/SKILL.md` as the model: 16 slots (1 problem, 14 purpose, 1 screens overview) written from the template alone, then `verify`, then `assemble`.

- Lint rounds needed: **0**. All 16 slots passed on the first run, and `prd.md` (368 lines) assembled.
- Caveat: the model here was the same session that wrote the lint rules, so a first-run pass is weak evidence about lint strength. The strength evidence is the negative tests (fabricated number, dead citation, citation outside range, fabricated quote, markdown structure, template injection, missing and extra keys).
- By hand: the group route counts in the Completion check sum to 78, the same figure as the gate; the `agent` group's first row matches the facts (`agent.controller.ts:29`).
- A reader would find this misleading or thin: the Problem slot is short because only the first README sections were offered (the draft states that 106 documentation sections were not offered, size cap); and "HTTP tests: none" for every Urus route reflects a real absence of HTTP tests rather than a linker miss.


## Slice 3 (client guide), 2026-10-14

Commands: `python3 -I bin/prd_facts.py <repo> --out ~/research/prd-out3/<name>` then `python3 -I bin/prd_draft.py guide-prepare <repo> --out ~/research/prd-out3/<name>`.
Numbers are from each run's `guide/guide_summary.json` after the fixes listed below. All three pass the guide gate.

| Repo | Screens | resolved / conditional / unresolved | with text | shared files | journey edges + shared-menu links | heading / button / label / placeholder / title / text / message | skipped candidates |
|---|---|---|---|---|---|---|---|
| room-management (Laravel + Vue) | 17 | 17 / 0 / 0 | 17 | 11 | 11 + 6 | 34 / 73 / 190 / 28 / 103 / 186 / 41 | 572 |
| Urus (NestJS + React) | 15 | 15 / 0 / 0 | 15 | 1 | 29 + 2 | 45 / 72 / 38 / 21 / 39 / 806 / 42 | 282 |
| tis (FastAPI + React), not golden | 21 | 18 / 2 / 1 | 18 | 4 | 16 + 11 | 86 / 140 / 120 / 35 / 108 / 542 / 188 | 414 |

### The slice 1 navigation fix worked

room-management had 0 navigation facts before (CodeGraph pointed all 20 at test-file routes). After re-attaching by path it has journey edges and shared-menu links (table above).

### Defects found by calibration and fixed (all test-first)

1. **CodeGraph's component link is wrong for nested Vue routes** (it points at the parent layout: `/admin/branches` resolved to `AdminLayout.vue`, so the view's own labels were missed). The router's own parsed expression now wins and the CodeGraph link is the fallback. This reverses the order in the spec.
2. **My first fix broke Urus** (its guide gate went from PASS to FAIL): Urus imports through barrel files (`from "../features/auth"` is an `index.ts` that only re-exports). A candidate file that does not declare the component is now followed through `export {...} from` and `export * from`; failing that, CodeGraph's link is used only if it names the same component.
3. **Components declared in the router file itself** (`tis` `App.tsx` defines `LoginPage`, `ViewerHomePage`, `AuthenticatedApp`) resolve to that file but contribute only the lines of their own declaration.
4. **UI-library attributes**: `label=` and `header=` are read (`label=` on a Button-like tag is a button). Before this, room-management showed 0 labels, placeholders and messages; now 190, 28 and 41.
5. **Strings in ternaries** (`{{ busy ? 'Signing out…' : 'Log out' }}`) are text. My own implementation first read class-name strings out of nested tags' attributes (`tis` `TeamsPage`); expressions containing a nested tag are now skipped for this rule.
6. **Icon-font noise**: snake_case ligature names and text inside `material-symbols`/`icon` elements are not text.
7. **HTML entities** are decoded (`Email &amp; Password` is shown as `Email & Password`).

### Hand checks

- Urus `/login`: the extracted items line up with `LoginPage.tsx` (messages at lines 49, 55, 60; placeholder at 189; labels at 182, 202; buttons at 209).
- room-management `/admin/branches`: heading, button "New branch", label "Search branches by code or name", placeholder "Search code or name" all come from `BranchesView.vue`.
- `tis` `/teams`: the seven "Failed to ..." messages come from `TeamsPage.tsx` catch handlers.

### Known limitations (documented, not fixed)

- **Messages kept in lookup tables are not found.** room-management's `http.ts` maps failures to client-visible text ("Cannot reach the server.", "Too many requests.", "Unexpected server response.", "Unknown error."). They sit in an object literal, not in a message call, so the name-based heuristic misses them. They appear in the skipped-candidates sample.
- **Text next to a dynamic value is a fragment.** `Batch Approve (` and `BATCH #PB-` are the static parts around an expression.
- **Developer-flavored text is shown as written.** Urus's login screen has the visible text `Fastify Guard:`. The guide is faithful to the screen; a person decides whether a client should see it.
- **`tis` has 3 non-resolved screens**, all catch-all `/*` wrapper routes around the signed-in app and the login page. They are not content screens.
- Depth-1 text only; translation files, roles and server-rendered views are not read.

### The full loop on Urus (acceptance run)

Followed `skills/client-guide-from-code/SKILL.md` as the model: 16 slots (1 overview, 15 screens; one answered `NEEDS HUMAN INPUT` because the evidence for `/agents` is a single loading message), then `verify`, then `assemble`.

- Lint rounds needed: **0**; `client-guide.md` assembled (967 lines, 15 screens, equal to the number of screens in the PRD facts).
- Caveat: same session that wrote the lint rules, so a first-run pass is weak evidence about lint strength. The strength evidence is the negative tests (jargon in prose, jargon inside quotes and citations, look-alike words, hostile UI text).
- A client might find odd: developer-flavored visible text such as `Fastify Guard:`, a screen heading list that includes "Not available for your role" (from a role-gate component imported by the home page), and fragment texts. The guide is faithful to the code, not curated.


## Slice 3b (developer guide), 2026-10-14

Commands: `python3 -I bin/prd_facts.py <repo> --out ~/research/prd-out4/<name>` then `python3 -I bin/prd_draft.py dev-prepare <repo> --out ~/research/prd-out4/<name>`.
Numbers are from each run's `dev/dev_summary.json` after the fixes listed below.

| Repo | Routes | Roles read / public / undeclared / not read | Request routes read | Raise sites attached | Screens joined to endpoints | Mismatches (roles / limits) | Dev gate |
|---|---|---|---|---|---|---|---|
| room-management (Laravel + Vue) | 66 | 63 / 0 / 3 / 0 | 38 of 53 | 49 of 118 | 9 of 17 | 0 / 0 | WARN |
| Urus (NestJS + React) | 78 | 73 / 5 / 0 / 0 | 56 of 60 | 67 of 250 | 0 of 15 | 0 / 0 | WARN |
| tis (FastAPI + React), not golden | 137 | 117 / 0 / 20 / 0 | 109 of 111 | 143 of 248 | 20 of 21 | 0 / 0 | WARN |

### Defects found by calibration and fixed (all test-first)

1. **First run: the dev gate FAILed on all three repos.**
   - `tis`: 117 of 137 endpoints were `not_read` because service and session factories passed to `Depends(...)` (`_get_service`, `get_db`) were treated as unreadable guards. They are plumbing; an endpoint with only plumbing is now `undeclared (open)` with a note naming the dependencies, and plumbing no longer hides a real guard next to it.
   - All three: `message_attachment` (raise sites attached over all raise sites) was below 0.50 because most raise sites sit in services more than one call deep, a stated non-goal. That check is now capped at `WARN` and never stops a run.
2. **room-management raises through static factories** (`throw ApiException::businessRule('CODE', 'message')`; the status is in the factory's `new self(422, ...)`). 3 of 20 sites were attached; the PHP extractor now reads the factory class, so the status, code and message come from the factory plus the call arguments (49 messages attached).
3. **`UploadFile`/`File(...)`/`Form(...)`** parameters on `tis` were reported as an unknown model; they are body fields.
4. **0 of 15 Urus screens were joined to an endpoint**, so no role or limit mismatch could ever be reported. Two causes: the join only looked at a screen's slice 3 evidence files (page and direct imports) while API calls sit in an api layer two imports away (now followed 2 further hops), and Urus uses a typed client (`api.payroll.list(...)`) that the slice 2 linker does not recognise (1 frontend call site found in the whole app). The second is not fixed; the guide and the summary now say how many screens were joined, so a silent mismatch check is not read as "no mismatches".

### Hand checks against the real code

- Urus `POST /api/v1/payroll/calculate`: roles `FINANCE, ADMIN` (from `@FinanceWrite()` through the `MONEY_WRITE` list in `@urus/types`); fields `period`, `workerId`, `employeeId` from `CalculatePayrollSchema`. `GET /api/v1/payroll`: all five roles (`@Authenticated()`).
- room-management `POST /api/v1/auth/login`: undeclared (open) with fields `email`, `password`; `GET /api/v1/branches`: `super_admin, branch_admin` with the `viewAny` ability; `PATCH /api/v1/houses/{house}`: `super_admin, branch_admin`, authorize check `move`, fields from the spread helper (`city`, `state`, `postcode`, `notes`, ...).
- `tis` `DELETE /api/v1/users/{user_id}`: roles `admin, developer` (from `require_admin` and `ADMIN_LIKE_TYPES`). The 20 undeclared endpoints are the open ones (`/health`, `/docs`, `/openapi.json`, `/api/v1/auth/login`, ...).

### Known limitations (documented, not fixed)

- Typed API clients (`api.payroll.list()`) are not linked to routes, so screens of such apps are not joined and mismatches are not checked for them.
- `tis` has no frontend role table or `meta.roles`; its 21 screens are all `not_read` for roles.
- Laravel: `permission:`/`ability:` middleware, controller-constructor middleware, and rules inherited from a base `rules()` (list requests: 15 of 53 request routes on room-management) are not read. Variable spreads of rule arrays (`...$required`) are not followed.
- NestJS: class-validator DTOs (`LoginInput`) and a schema defined more than once are not read. Messages in services more than one call deep are not attached (Urus: 67 of 250 raise sites).
- FastAPI: router-level `dependencies=` are noted, not followed; validators are noted, not read.
- Hand-written input checks and messages computed at run time are not read.

### The full loop on Urus (acceptance run)

Followed `skills/developer-guide-from-code/SKILL.md` as the model: 15 slots (1 overview and 14 route groups; 3 answered `NEEDS HUMAN INPUT` because their evidence is a single "anyone" line or does not state a purpose), then `verify`, then `assemble`.

- Lint rounds needed: **0**; `developer-guide.md` assembled (264 lines, 14 groups, equal to the number of route groups in the facts).
- `POST /api/v1/payroll/calculate` appears with roles `FINANCE, ADMIN` and the three zod fields; no table cell contains an unescaped `<`.
- Caveat: same session that wrote the lint rules, so a first-run pass is weak evidence about lint strength. The strength evidence is the negative tests (hostile message text, quotes not in the cited evidence).
- What a reader should know: the guide says 0 of 15 screens were joined to endpoints, so its mismatch tables are empty because nothing was checked, not because nothing differs.

### After the final review

The fresh whole-branch review found, and these fixes closed (each with a failing test first):

- FastAPI `Depends(require_role("admin"))`, `Depends(factory(...))` and `Security(..., scopes=...)` were dropped and the endpoint reported as open; they are now `not_read`.
- A dependency that raises something other than a recognised `HTTPException`, or uses a security scheme, is no longer called plumbing; a 403 guard whose comparison is not about a role-like attribute (`user.id != item.owner`) is no longer read as a role list.
- Role lists with a call, a template or any unparseable part (`@Roles(getRoles())`), an empty `@Roles()`, Laravel `'role:'.$x`, dynamic middleware arguments and `withoutMiddleware` are `not_read`; `role:a|b` is split on the pipe.
- An endpoint with an empty role list can no longer produce a mismatch claim; mismatch wording now says how the screen was joined.
- `dev-prepare` and `guide-prepare` now remove their older outputs before any validation, so an early failure cannot leave a guide that `assemble` accepts.
- Quadratic scans were bounded (a 217 KB nav file took 62 s, a 670 KB constants file 62 s); Laravel route groups are computed once per routes file.
- `Annotated[User, Depends(get_user)]` no longer produces body fields; NestJS `@Body(new ValidationPipe())`, `@Req()` and other unrecognised parameter decorators are `not_read` (two Urus upload endpoints moved from "read" to "not read"); `z.coerce.x()`, exclusive bounds and unparseable zod chains are handled; an unknown status renders as `?`; "undeclared" is worded as "found no declaration" instead of a bare "open".


## Slice 4 (criteria candidates for team-task), 2026-10-14

Commands: `python3 -I bin/prd_criteria.py build <repo> --state-dir ~/research/prd-state`, then `lookup <repo> "<task>" --state-dir ~/research/prd-state`. A full build (slice 1 facts, slice 3b facts, bank) takes 1 to 3 seconds on these three repos.

| Repo | Routes | Screens | Candidates | By kind | Role universe |
|---|---|---|---|---|---|
| room-management (Laravel + Vue) | 66 | 17 | 278 | error 49 / field 126 / request_unread 15 / role 66 / role_refused 13 / screen_roles 9 | laravel 2 |
| Urus (NestJS + React) | 78 | 15 | 343 | error 67 / field 114 / request_unread 4 / role 78 / role_refused 67 / screen_roles 13 | nestjs 5 |
| tis (FastAPI + React), not golden | 137 | 21 | 866 | error 434 / field 268 / request_unread 2 / role 137 / role_refused 25 | fastapi 2 |

### Task sentences tried against the real code

| Repo and sentence | What the lookup returned | Verdict |
|---|---|---|
| Urus "let managers approve payroll" | first subject `POST /api/v1/payroll/:id/approve`: allowed for `FINANCE, ADMIN`; `MANAGER`, `HR`, `WORKER` shown as refused (derived, with the trust note naming the universe) | exact; the derived refusal of `MANAGER` is the criterion the task needs to change |
| tis "only admins can delete users" | first subject `DELETE /api/v1/users/{user_id}`: allowed for `admin, developer`; messages 404 'User not found', 403 'Admin access required', 401 from the guard | exact |
| room-management "let branch admins deactivate a house" | `POST /branches/{branch}/deactivate` (super_admin only; `branch_admin` refused, derived) ranks first, `POST /houses/{house}/deactivate` (`super_admin, branch_admin`) second | both present; "branch" is a path word and a role word, so the branch endpoint ties on the literal words |
| room-management "tenants can see their own rooms" | tenancy and room endpoints for admins; the tenant self-service group is empty in the code (`role:tenant` group has no routes yet) | correct: the code has nothing for this, and the output shows it |
| Urus "reject receipt scanning for large files" / "scan a receipt with ocr" | `POST /ocr/receipt` is among the top three subjects for both; first for "ocr", tied for "scanning" | works; "scanning" is not reduced to "scan" |

### Decisions found by calibration

1. **A mismatch no longer makes its screen look like a match for the endpoint's words.** The plan's own ranking test showed `screen /payroll` outranking `POST /api/payroll/calculate` for "let finance managers calculate payroll", because the screen's mismatch candidates carry the endpoint's path words. A screen is now scored by its own path and roles only, and a mismatch is listed under the screen and under the endpoint it concerns.

### Known limitations

- Matching is literal after a light plural stem: "scanning" does not match "scan", "pay run" does not match "payroll". A word that is both a path word and a role word (`branch`) selects by the path.
- Ids (`C-ROLE-014`) are only valid for the commit printed beside them.
- Derived refusals depend on the role universe (the roles seen on read endpoints of the same stack). A stack where one role never appears on a read endpoint cannot be refused it.
- Typed API clients leave screens unjoined (0 of 15 on Urus), so mismatch candidates are rare there.

### After the final review (slice 4)

The fresh whole-branch review found no critical issue and these important ones, closed test-first: the freshness fingerprint did not notice edits to quoted or non-ASCII paths, a repo argument that is a subdirectory, commits inside a nested repository, or a same-size rewrite that keeps its mtime; a corrupt `meta.json` or `criteria.json` gave a traceback (and the draft only handles exit 0, 2 and 3) or never healed; leftover `.old-*` and `.build-*` directories and a cache swapped away between check and read broke rebuilds; the derived-refusal wording claimed more than is known; `show` printed hostile text unescaped. Still open (documented): facts built from a CodeGraph database that lags the working tree are marked fresh, `TOOL_VERSION` is bumped by hand, and git-ignored files are invisible to the fingerprint.
