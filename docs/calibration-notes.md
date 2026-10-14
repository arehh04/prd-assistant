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
