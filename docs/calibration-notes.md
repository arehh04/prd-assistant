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
