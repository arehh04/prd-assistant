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
