# PRD Assistant, Slice 3: Client guide

Date: 2026-10-14
Status: DRAFT for review. No slice 3 code exists yet.
Parent specs: `design.md` (section 7, "Client guide"), `design-slice2.md` (scaffold plus prose slots, lint, manifest).
Process so far: scope option 1 and this design were approved in conversation on 2026-10-14. Option 3 (roles, form rules, backend messages) is the **developer version**, deferred (section 13).

## 1. Purpose

Turn a repo that passed the slice 1 gate into a **plain-language client guide**: for each screen, how to get there, what is on it (quoted verbatim from the code), what the client may be told when something goes wrong, and where to go next. The reader is a client who wants to use the product without failing, not an engineer.

Rule inherited from slices 1 and 2: structure, counts, quotations and citations are computed by scripts; the model writes only short prose slots, which a lint script checks. A new rule for this audience: the prose must not use engineering jargon.

## 2. Evidence this design rests on (2026-10-14)

- Navigation facts exist for Urus (27, of which 13 of 15 screens have incoming navigation) and `tis` (26), but room-management has **0**: CodeGraph resolves its 20 navigation edges to route nodes in a test file (`frontend/src/__tests__/mount.ts`), so slice 1 dropped them as `target-excluded` (deferred in `docs/calibration-notes.md`). The same screens exist under real paths, so the targets can be re-attached by path.
- Mapping a screen to the component that renders it works in all three frontends, by three mechanisms:
  - Urus (React object routes): CodeGraph's route node has a `references` edge to the page (`/login` to `LoginPage`).
  - `tis` (JSX `<Route element={...}>`): no edge. The element is an expression such as `isViewer ? <ViewerHomePage/> : <Suspense><NewSearchPage .../></Suspense>`.
  - room-management (Vue): `component: () => import('@/views/admin/branches/BranchesView.vue')` with the alias `'@'` defined in `vite.config.ts`. The route's `meta: { title: 'Branches' }` is also user-visible text.
- User-facing text exists in the code: about 567 text-like items in Urus's web app, for example "Could not load agent findings. The floor above is idle, not clear."
- Guards exist but are not uniform (`<RequireRole roles={rolesForPath(pathname)}>` in Urus, `meta.roles` in Vue). Reading them is per-framework work and belongs to the developer version.

## 3. Non-goals

- No roles or permissions (who may use a screen), no form rules or validation messages, no backend error messages, no API reference: all developer version (section 13). The guide says "Who may use each screen: NEEDS HUMAN INPUT".
- No server-rendered views (Blade, Twig, Django templates): the guide states that they are not read.
- No translation files: if the repo uses an i18n library the guide warns that text comes from files this version does not read.
- No proof that the prose is true or that the labels shown are visible in every state of the app.
- No screenshots or live app execution. The tool reads files only.

## 4. Pipeline

```
prd_facts.py            (slice 1)  -> facts.json, gate.json                 FAIL stops
prd_draft.py guide-prepare REPO --out OUT
    ui_text.py          (new)      -> OUT/guide/ui_text.json
    journeys.py         (new)      -> OUT/guide/journeys.json
    guide.py            (new)      -> OUT/guide/guide_gate.json, guide_gate.md,
                                      scaffold.md, slots.template.json, manifest.json, guide_summary.json
model fills slots                  -> OUT/guide/slots.json
prd_draft.py verify   --out OUT/guide
prd_draft.py assemble --out OUT/guide  -> OUT/guide/client-guide.md
```

- `verify` and `assemble` are the slice 2 commands. The only changes: `manifest.json` records `kind` (`prd` or `guide`) and `assemble` names its output `prd.md` or `client-guide.md` accordingly; `verify` gains the jargon rule (section 9).
- A slice 1 gate FAIL, or a guide gate FAIL, stops with exit code 2 and writes no scaffold, template or manifest (on a guide gate FAIL the diagnostic files `ui_text.json`, `journeys.json` and the guide gate report are still written, so the cause is visible). A repo with no screens exits 3 with "no screens were extracted; the client guide needs a frontend".
- Exit codes are unchanged: `0` ok, `1` lint failures, `2` gate FAIL, `3` environment or input error.

## 5. Slice 1 fix: re-attach navigation (prerequisite)

In `extract.extract_facts`, a navigation edge whose target route node is excluded (a test-file route) is re-attached to the unique non-excluded screen with the same `path`. If there is not exactly one such screen it stays excluded with reason `target-excluded`. The fact gains `"reattached": true`. Effect: room-management gains up to 17 navigation facts; the route and screen counts and the gate are unchanged.

## 6. Finding what a screen shows (`ui_text.py`)

### 6.1 The component for a screen

Tried in this order; the first that yields candidates wins.

1. A CodeGraph `references` edge from the screen's route node to a function, class or component node.
2. The route's expression, read from the router file starting at the route's line:
   - JSX: the `element={...}` attribute text up to its balanced closing brace; every capitalized tag name inside it, except the wrappers `Suspense`, `Navigate`, `Fragment`, `Outlet`, `ErrorBoundary`, `Route`, `Routes` (and `React.*` wrappers). Several names means a conditional screen; all are kept and labelled `conditional`.
   - Object routes: `element: <Name .../>` or `component: Name` (the first identifier).
   - Vue: `component: () => import('<path>')` or `component: Name`.
3. Otherwise the screen is `unresolved` and nothing is invented.

A component name becomes a file via the router file's own `import` statements, then CodeGraph's `nodes` (a unique node of that name), then nothing. An `import('<path>')` path is resolved relative to the router file, or through an alias taken from the repo's own configuration: `resolve.alias` in `vite.config.*`, or `compilerOptions.paths` in `tsconfig*.json`. An alias that is not configured is not guessed.

### 6.2 Which files supply a screen's text

The component file plus the repository files it imports directly (depth 1): static `import` statements that are relative or resolve through a configured alias, with suffix `.tsx`, `.jsx`, `.vue`, `.ts` or `.js`, inside the repo, not test files, not generated, not symlinks. Per screen at most 40 files and 300 strings; beyond that `truncated: true` is recorded and shown.

A file used by more than one third of the resolved screens (and by at least 3) is **shared** (layouts, sidebars). Its text is listed once under "On every screen" and not repeated per screen.

### 6.3 Text kinds

Each item is `{kind, text, file, line}`. Text is whitespace-normalized; items with no letter are dropped; repeated identical items in one file are kept once.

| Kind | Source |
|---|---|
| `heading` | JSX/template text whose nearest open tag is `h1`..`h6` or a name containing `Title`/`Heading`; router `meta.title` (kind `title`) |
| `button` | text inside `button`, `a`, or a tag whose name contains `Button` or `Link` |
| `label` | text inside `label` or a tag named `*Label`; the `label=` attribute |
| `placeholder` | `placeholder=` attribute |
| `title` | `title=`, `aria-label=`, `alt=` attributes |
| `text` | any other text node with a letter |
| `message` | every string literal inside the argument text of a call whose name contains `toast`, `error`, `alert`, `notify`, `snack`, `warning` or `success` (case-insensitive), and text inside an element with `role="alert"` or a `class`/`className` containing `destructive` or `error` |

`message` is labelled "likely message (by call or element name)". It is a heuristic, not proof that a client will see it.

Attributes that never carry visible text are skipped: `className`, `class`, `style`, `key`, `id`, `name`, `type`, `href`, `src`, `to`, `path`, `variant`, `size`, `data-*`, and any string in an `import`/`export ... from` line. Where a component is written `{"text"}` the string is taken like a text node.

JSX/TSX/JS and Vue single-file components (the `<template>` block) are read. Other front-end technologies are `unsupported` and reported as such in the gate.

### 6.4 i18n

If `package.json` lists `react-i18next`, `i18next`, `vue-i18n` or `@lingui/core`, or a call `t('...')`/`$t('...')` occurs in a screen's files, the gate adds a WARN: "this repo keeps UI text in translation files, which this version does not read". Keys are not presented as text.

### 6.5 Output (`ui_text.json`, `schema: 1`)

```
{ "schema": 1,
  "i18n": {"detected": bool, "evidence": [...]},
  "shared_files": [{file, used_by}],
  "screens": { "<screen id>": { "path", "status": "resolved"|"unresolved"|"conditional",
                                "component_file", "candidates": [...], "files": [...],
                                "truncated": bool, "items": [{kind, text, file, line}] } },
  "shared_items": [{kind, text, file, line}],
  "skipped_candidates": {"count": n, "sample": [{file, line, text}]} }
```

`skipped_candidates` come from a looser independent regex (any string of two or more words in a string literal or text node that the main extractor did not take, outside the skipped attributes). It is a visibility check, not a gate, as in slice 2.

## 7. Journeys (`journeys.py`)

- Input: navigation facts (after section 5) and `ui_text.json`.
- A navigation fact belongs to screen A when its `from_file` is one of A's non-shared evidence files. If the file belongs to several screens' evidence (and is not shared) all of them get the edge. If the file is shared (or belongs to no screen), the edge is reported as **shared navigation** with its source file, for example a menu.
- Output (`journeys.json`): `edges: [{from_screen, to_screen, via: "file:line", label}]` where `label` is a `button`/`title` item on the same line when there is one; `shared: [{to_screen, via}]`; and per screen `reached_from` and `leads_to`.

## 8. Scaffold (`guide.py`), all computed

1. **Trust header.** Slice 1 gate verdict, guide gate verdict and each check, counts (screens, resolved, with text, shared files), the i18n warning if any.
2. **Screens at a glance.** Table: screen id and path, headings or titles (verbatim), reached from, leads to.
3. **One section per screen** (resolved screens with at least one item): slot `screen.Sxx`, then two verbatim tables with `file:line`: "What you will see" (headings, buttons, labels, placeholders, titles) and "Messages you may see" (`message` items, flagged as likely). A conditional screen lists every candidate name. A truncated screen says so.
4. **On every screen.** The shared items, once.
5. **If something goes wrong.** Every `message` item in the repo, with the screen it appears on.
6. **Gaps.** Screens that are unresolved or have no text, unsupported technologies, and `Who may use each screen: NEEDS HUMAN INPUT`.

Group ids reuse slice 2's `groups.group_screens` (`S01`...). Every repo-controlled string passes through slice 2's `esc`/`cell` helpers before it enters the scaffold.

## 9. Slots and lint

- Slots: `overview` (at most 80 words; evidence = the headings and titles of all resolved screens, capped at 24,000 characters like the PRD problem slot) and `screen.Sxx` (at most 60 words; evidence = that screen's items). Both may be `NEEDS HUMAN INPUT`. The template is built with the slice 2 `slots.template.json` shape plus two fields per slot: `banned_terms` and `audience: "client"`.
- All slice 2 lint rules apply unchanged (one plain line, citations resolve, digits from the evidence, quotes verbatim, keys exact).
- **New rule `jargon`.** Text with citations and double-quoted strings removed must not contain a banned term as a whole word, case-insensitively. Default list (a starting value, stored in the template): `api, endpoint, endpoints, route, routes, handler, component, components, controller, backend, frontend, json, http, https, database, sql, token, schema, payload, request, response, status code, repository, repo, module, function, regex, boolean, null, async`. A client-facing sentence may quote a label that contains a banned term, because quoted strings are excluded.
- Instructions given to the model (in the template): write for a person who has never seen the code; say what the person does on the screen in plain words; quote button and label names exactly; do not describe how the program works; if the labels do not make the purpose clear, answer `NEEDS HUMAN INPUT`.

## 10. The guide gate (`guide_gate.json`)

All computed, thresholds are starting values to calibrate.

| Check | Computation | PASS | WARN | FAIL |
|---|---|---|---|---|
| `component_resolution` | resolved or conditional screens / all screens | >= 0.90 | >= 0.50 | < 0.50 |
| `text_coverage` | resolved screens with at least one item / resolved screens | >= 0.90 | >= 0.50 | < 0.50 |
| `i18n` | section 6.4 | none detected | detected | none |
| `unsupported_tech` | screens whose component file is not JSX/TSX/Vue | 0 | any | none |
| `navigation_reach` (info) | screens with an incoming edge or shared navigation | listed | | |
| `skipped_candidates` (info) | count and sample | listed | | |
| `truncation` (info) | screens whose evidence was capped | listed | | |

Verdict is the worst graded check. FAIL stops the pipeline. With zero screens: exit 3 (section 4).

## 11. Errors and edge cases

| Case | Behavior |
|---|---|
| Repo has no screens | exit 3, nothing written |
| Router file unreadable or screen's file missing | screen `unresolved`; counted in the gate |
| A component imported from outside the repo or a `node_modules` package | not followed |
| A screen's text is only in a shared file | the screen section says "uses only shared elements" |
| Import cycles | depth 1 only; no recursion |
| Binary or huge component file (over 2 MB) | skipped, reported as unreadable (as in slices 1 and 2) |
| Slot text copies an instruction found in a UI string | lint cannot see this; mitigated by delimiters and JSON-only replies, as in slice 2 |

## 12. Testing

- Unit tests with fixtures: component resolution for each mechanism (CodeGraph edge, JSX element with ternary and wrappers, object route, Vue `import()` with alias, unresolved); each text kind and each skipped attribute; message heuristics; Vue template; shared-file detection; truncation; i18n detection; navigation re-attach (slice 1 extract test); journey edges including shared navigation; scaffold placeholders; the guide gate thresholds; the jargon rule (positive and negative); the CLI end to end including gate FAIL writing nothing and no-screens exit 3.
- Negative lint tests for the jargon rule: banned term in prose fails; banned term inside a quoted label passes; banned term in a citation path passes; word-boundary cases (`application` must not trip `api`).
- Golden results added to `calibration/calibration.json` for room-management and Urus: screens resolved, screens with text, item counts by kind, shared files, journey edge counts. `tis` is documented, not golden.
- Acceptance: on Urus the loop (prepare, fill slots, verify within 2 repair rounds, assemble) completes, and the guide's screen count equals the PRD's.

## 13. Developer version (deferred, its own slice)

`design-slice3b` will cover: who may use each screen (guards: `RequireRole`, `meta.roles`, middleware), form rules (required fields and validation messages from schemas such as Zod, Pydantic, Laravel requests), the backend error messages a client may see, and an endpoint reference. It reuses this slice's component resolution and extraction, adds per-framework parsers, and gets its own calibration. Not built now.

## 14. Risks and open questions

- Depth-1 text misses text rendered by deeper components. The gate's `text_coverage` and the skipped-candidates sample make this visible; a deeper walk is a later option.
- The message heuristic is name-based. A custom `notifyUser` helper is found by the word `notify`, but a helper named `show` is not.
- Conditional screens list several candidates; the guide cannot know which the client sees.
- The jargon list is a judgment call and will need tuning on real output.
- Text kinds are guessed from tag names; a design-system component named `Foo` with a title prop is read as a `text` item.
- Vue templates are read with patterns, not a real parser; unusual syntax may be skipped, and the skipped-candidates sample is where that shows.

## Amendments from the slice 3 plan and calibration (2026-10-14)

1. Component files come from the router's own parsed expression and imports; CodeGraph's route link is only the fallback (it points at the parent layout for nested Vue routes) and is used for a candidate only when it names the same component. A candidate file that does not declare the component is followed through `export {...} from` and `export * from` (3 hops).
2. Screens are numbered individually (`S01`...) sorted by path; slice 2's per-segment group ids are not used.
3. Calls whose name is a `*Error`/`*Exception` constructor, and `console.*`/`logger.*`, are not client-visible messages.
4. `mask(..., apostrophe_in_words=True)` treats an apostrophe between letters as text.
5. A `Component:` route key is read like `component:`.
6. A resolved screen with no text of its own is listed under Gaps instead of getting a section.
7. The default banned list also contains `apis`.
8. A component declared in the router file itself resolves to that file and contributes only its own declaration's lines.
9. `label=` and `header=` attributes are read; strings after `?`/`:` inside a text expression are text unless they look like code tokens and unless the expression contains a nested tag; snake_case icon names and text inside icon-font elements are not text; HTML entities are decoded.
