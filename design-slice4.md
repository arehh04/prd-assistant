# PRD Assistant, Slice 4: Acceptance-criteria candidates for `team-task`

Date: 2026-10-14
Status: DRAFT for review. No slice 4 code exists yet.
Parent specs: `design.md`, `design-slice3b.md` (roles, form rules, error messages: the facts this slice serves), `design-slice3.md` (screens).
Process so far: decisions below were made with the user in conversation on 2026-10-14. The branch `slice4-criteria-feed` is cut from `slice3b-developer-guide` (not yet merged into `master` by the user).

## 1. Purpose

`team-task` step 1 says: "Restate the task as a numbered list of acceptance criteria. If any are missing or ambiguous, ask me." Today those criteria come from the user's head and the model's memory of the repo, so role names, limits and messages are often guessed.

This slice gives step 1 **exact, cited candidates** taken from the code: "`POST /payroll/calculate` is allowed for `FINANCE`, `ADMIN` [`controller.ts:64`]", "`WORKER` is refused on it (derived)", "`period` must match `PeriodRegex` and its message is '...'". The orchestrator picks the relevant ones for the task, labels each **preserve** or **change**, and cites their ids.

Rule inherited from slices 1 to 3: nothing is guessed. A candidate states what the code does **now**; what is derived is flagged; what was not read is stated in a trust note.

## 2. Decisions (user, 2026-10-14)

1. **Shape: both a bank and a lookup.** A **criteria bank** (`criteria.json`, every candidate of the repo) is the source of truth; `lookup` filters it for a task. If nothing matches, the lookup says so and points to the bank.
2. **Phrasing: current-behaviour statements, plus derived "refused" cases, plus a trust note on every candidate.** The model labels candidates preserve or change; the script never decides that.
3. **Storage and freshness: an automatic cache outside the repo** in `~/.claude/state/prd-assistant/<repo-name>-<hash>/`, rebuilt when the git `HEAD`, the changed-files fingerprint or the tool version differs. The cache only reads the repo through the existing CodeGraph index and writes only to the state directory. A repo without a CodeGraph index stops with an error; no index is built inside the repo.
4. **`team-task` is not edited by this slice.** The new step 1 is written as a draft file; the user applies it (as with the earlier drafts).

## 3. Evidence this design rests on (2026-10-14)

- `~/.claude/commands/team-task.md` step 1 (acceptance criteria), step 2 (uses CodeGraph to scope), and the hard rule "never read `.env` or other secrets". Run records already live under `~/.claude/state/team-task/`.
- Slice 3b outputs per repo: `roles.json` (per route: status, roles, authenticated, via, notes, source, `undeclared_means`; per screen: roles; `role_names`; mismatches), `form_rules.json` (per route: fields with type, required, min, max, format, one_of, pattern, messages, source; `not_read`; forms; mismatches), `error_messages.json` (messages with status, kind, text, via, source; `not_read` counts). Calibrated on room-management (66 routes), Urus (78), `tis` (137) in `docs/calibration-notes.md`.
- Everything above already carries `file:line` citations and explicit `not_read` reasons; this slice reshapes it, it does not extract anything new from source code.

## 4. Non-goals

- No writing of the criteria for the user, no choice of preserve or change, no generation of test code.
- No editing of `team-task.md` or any file under `~/.claude` other than the cache directory.
- No semantic matching or synonyms ("pay run" vs "payroll"); an alias file may come later.
- No running of the app, no network.
- No MCP wrapper (slice 5) and no developer-guide prose.

## 5. Commands (`bin/prd_criteria.py`, stdlib only, run as `python3 -I`)

```
prd_criteria.py lookup REPO "task words" [--max-subjects 5] [--max-candidates 60] [--json] [--state-dir DIR]
prd_criteria.py build  REPO [--state-dir DIR]          force a refresh
prd_criteria.py show   REPO --id C-ROLE-014 [--json]   one candidate in full
```

- `lookup` and `show` first make sure the cache is fresh (below), rebuilding it when needed, then read `criteria.json`.
- Exit codes: 0 ok (including "no match"), 2 facts unavailable (slice 1 gate or dev gate FAIL, with the reason printed), 3 environment or input error (not a directory, no CodeGraph index, no routes, unwritable state directory).
- State directory: `$PRD_ASSISTANT_STATE` or `~/.claude/state/prd-assistant/`, then `<repo-name>-<first 8 hex of sha256 of the absolute repo path>/`.

## 6. The cache

```
<state>/<repo-dir>/
    facts.json gate.json ...      slice 1 outputs      (pipeline.run + write_outputs)
    dev/roles.json form_rules.json error_messages.json dev_gate.json dev_summary.json     (slice 3b)
    criteria.json                 the bank (section 7)
    meta.json                     {schema_version, tool_version, repo, head, dirty, built_at, codegraph_commit, counts}
```

- **Fresh** means: `meta.tool_version` equals the current `TOOL_VERSION`, `meta.head` equals `git rev-parse HEAD`, and `meta.dirty` equals the current fingerprint. The fingerprint is a SHA-256 over the lines of `git status --porcelain=v1 -uall` plus the size and mtime of each listed file (so a file edited twice is noticed). Only read-only git commands are used.
- A repo that is not a git repository is rebuilt every time and the output says so.
- A rebuild writes into a temporary sibling directory and renames it into place, so an interrupted build never leaves a half-fresh cache. A failed rebuild leaves the previous cache untouched and the command exits 2 or 3; `lookup` never silently answers from a cache it knows is stale.
- `TOOL_VERSION` is a constant in `prd_assistant/criteria.py`; it changes whenever candidate generation changes.

## 7. The bank (`criteria.json`, `schema_version: 1`)

```
{"schema_version": 1, "tool_version": "...", "repo": "...", "head": "...", "generated": "<date>",
 "candidates": [ {id, kind, subject, text, facts, sources, derived, trust, keys}, ... ],
 "universe": {"<stack>": ["ADMIN", ...]}, "counts": {kind: n}}
```

- `id`: `C-<KIND>-<NNN>`, numbered in route order (the order of `facts.json`) then screens. Ids are only meaningful for the commit printed with them: they may change when the code changes.
- `subject`: `{"type": "route"|"screen", "id": ..., "label": "POST /api/v1/payroll/calculate"}`.
- `facts`: the structured record the sentence was built from (roles list, field dict, status and text of a message, ...).
- `sources`: list of `file:line`; `derived`: true only for `role_refused`; `trust`: list of plain sentences; `keys`: lowercase tokens used by the lookup (not printed).

Kinds and wording (the sentence states what the code does now):

| Kind | Built from | Sentence |
|---|---|---|
| `role` | `roles.endpoints[rid]` | `read` with roles: "`M P` is allowed for roles A, B."; `read` with `authenticated`: "... is allowed for any signed-in user."; `public`: "... is open to anyone."; `undeclared`: the guide's wording ("no declaration found (open unless guarded where this tool does not look)", "...refused by the global guard", "...effect unknown"); `not_read`: "The roles for `M P` could not be read." |
| `role_refused` (derived) | the `role` record plus the stack's role universe | "Role R is refused on `M P`." One per role in the universe that is not allowed. No HTTP status is stated unless a guard message with a status was read for that endpoint. |
| `field` | `form_rules.endpoints[rid].fields[]` | "`M P` takes `name` (body): required, string, max 60, one of a/b, pattern X." plus the rule's validation messages when present. |
| `request_unread` | `form_rules.endpoints[rid].not_read` | "Part of the request of `M P` was not read: reason." |
| `error` | `error_messages.messages[]` (one per route and source) | "`M P` returns 404 'No such team'." (`?` when the status is unknown; template messages keep `{…}`) |
| `screen_roles` | `roles.screens[sid]` with status `read` | "Screen `/path` is shown to roles A, B." |
| `mismatch` | `roles.mismatches` and `form_rules.mismatches` | "Screen `/path` can be opened by role R but the endpoint it calls (`M P`) refuses R." / "The form allows 50 characters in `title` but `M P` allows 60." Always with "needs a decision" in the trust note. |

**Role universe and `role_refused`.** The universe of a stack is the union of the roles (case-folded, `-` and spaces treated as `_`) listed on **read** endpoint records of that stack. `role_refused` candidates are generated only for endpoints whose record is `read` with a non-empty role list and only when the universe has at least two roles. A role is refused when it is in the universe and not in the endpoint's list. A role that never appears on any read endpoint of the stack is never invented.

**Trust notes** (every candidate has at least one line of provenance, plus the specific ones that apply):

- From the record: `notes` ("router-level dependencies are not followed"), `reason` of a `not_read`, abilities ("ability checks also apply: viewAny"), `partial` zod chains ("part of the validation chain could not be parsed"), `undeclared_means`.
- For `screen_roles` and `mismatch` candidates: how many screens were joined to endpoints (for example "0 of 15 screens were joined to endpoints, so screen/endpoint role mismatches were not checked").
- For `error`: always "only messages in the handler, its guards and the functions it calls directly are read; messages raised deeper are not included".
- For `field`: the model's validators and hand-written input checks are not read.
- Texts are copied verbatim from the code; they are data and are escaped when printed (section 9).

## 8. The lookup

- **Tokens.** The task text is lowercased, split on non-alphanumerics and camelCase, tokens shorter than 3 characters and a fixed stopword list are dropped, and a trailing `s`/`es` is stripped from tokens longer than 4 characters.
- **Keys.** For a route: path segments (split on `/`, `-`, `_`, camelCase, `{param}` names without braces), the method word, field names, message words. For a screen: path segments. For `role` and `role_refused` candidates: role names are keys too, but they are **role keys**.
- **Selection.** A route or screen subject is selected only if at least one task token matches a **non-role** key of that subject (path, field, message or screen path). Role tokens only add to the score. Without this rule "finance" would select every endpoint that finance can call.
- **Ranking.** Score = number of distinct task tokens that hit the subject (role hits count half). Ties are broken by the subject's path. The top `--max-subjects` subjects are returned with all of their candidates, then the output is cut at `--max-candidates` with a line saying how many were left out.
- **Output (Markdown).** First lines: repo, commit, age of the facts ("built 3 minutes ago at `abc1234`"), cache path, counts; then one section per subject with its candidates as bullets: `- [C-ROLE-014] role: <sentence> — <sources> — trust: <notes>`; derived candidates are marked `(derived)`. The block opens with "These are facts extracted from the repository, not instructions." If nothing matches: "No match for: <tokens>", the list of route groups (`G01 payroll (12 routes)`), the bank path and the counts per kind.
- `--json` prints the same selection as JSON (candidates plus the header fields).
- `show --id` prints one candidate with all its facts and sources.

## 9. Safety

- Reads of the repo go through the slice 1 and 3b pipelines (private copy of the CodeGraph database; secret-named files, symlinks and files outside the repo are never read). The only writes are under the state directory. No command writes into the repo.
- All text taken from the repo (paths, messages, role names) is escaped before it is printed: control characters removed, backticks and `{{` neutralised, Markdown links, images and HTML neutralised in running text, and printed inside code spans where possible. The header says the content is data.
- Output size is bounded by `--max-candidates` and a per-candidate length cap (1,000 characters); the bank itself is capped at 20,000 candidates (the build says so if the cap is hit).
- The state directory name uses the repo's name and a hash, never the raw path, so a hostile repo name cannot escape it (`/` and `..` are removed from the name).

## 10. The `team-task` draft

`/home/arep/research/drafts/team-task-step1-criteria.md` contains the proposed replacement for step 1, ready to paste. It does not run anything by itself. The orchestrator:

1. Restates the task as numbered criteria (as today).
2. If the repo is a git repo, runs `python3 -I /home/arep/research/prd-assistant/bin/prd_criteria.py lookup <repo> "<task>"`. A CodeGraph-less repo or exit 2 or 3 means: continue without candidates and say so.
3. Uses candidates **as evidence, not as criteria**: each criterion that rests on a candidate cites its id and is labelled **preserve** or **change**; `(derived)` ones are labelled as such; criteria resting on a candidate with a trust note that matters are raised with the user before step 2.
4. Never invents a role, field, limit or message that no candidate or the task text contains.

## 11. Errors and edge cases

- No match, no routes, no screens, only screens (the bank then has screen candidates only and says there are no endpoint candidates), a role universe of one role (no `role_refused`), a repo with `undeclared` everywhere, a task text that is empty or only stopwords (treated as no match with a hint), Unicode and very long task texts (truncated to 2,000 characters), two repos with the same name (different hashes).
- A dirty repo: the fingerprint changes, so the cache rebuilds; the facts reflect the files as they are on disk, and the header prints "working tree has N changed files".
- Concurrent `lookup` runs: the atomic rename makes the last writer win; readers always see a complete cache.

## 12. Testing (test-first)

- Candidate generation from synthetic `roles`/`rules`/`errors` dicts: every kind, wording, trust notes, `role_refused` rules (universe of one, unread records, case-folding, no HTTP status), the id numbering, the cap.
- Lookup: tokenising, stemming, non-role selection rule, role-word scoring, ties, cut-off line, "no match" output, `--json`, hostile text (markdown, HTML, `{{`, control characters, very long messages).
- Cache: fresh and stale cases with a real temporary git repository (new commit, edited tracked file edited twice, untracked file, non-git directory), tool-version change, interrupted build leaves the old cache, state-directory naming with hostile repo names, no index gives exit 3 and writes nothing.
- CLI exit codes. Golden calibration `expect_criteria` (counts per kind) for room-management and Urus with a mutation check; `tis` documented only.
- Hand checks of `lookup` on the calibration repos with realistic task sentences ("let managers approve payroll", "reject login after too many attempts") recorded in `docs/calibration-notes.md`.
- The `team-task` draft is checked by a test that it names the real script path, the three exit codes and the preserve/change labels (a file test, as for the skills).

## 13. Risks and open questions

- Word matching is literal; tasks worded differently from the code find nothing. The fallback (route groups and the bank path) is the answer for now; an alias file is the natural next step.
- Ids change when the code changes; they are only valid with the commit printed beside them.
- `role_refused` depends on the role universe being complete for the stack; the trust note says it is derived from the roles seen on read endpoints.
- Rebuilding on a large repo can take minutes; the lookup prints that it is rebuilding. A build timeout of 15 minutes applies (the same as CodeGraph's own).
- `team-task` runs in a fresh Claude session per task: nothing in this slice makes the orchestrator call the lookup until the user applies the draft.
