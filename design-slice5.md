# PRD Assistant, Slice 5: MCP server

Date: 2026-10-14
Status: DRAFT for review. No slice 5 code exists yet.
Parent specs: `design-slice4.md` (criteria bank, lookup, cache), `design-slice3b.md`, `design.md`.
Process so far: decisions below were made with the user in conversation on 2026-10-14. The branch `slice5-mcp-server` is cut from `slice4-criteria-feed`; neither slice 3b nor slice 4 is merged into `master` yet.

## 1. Purpose

Slice 4 gives `team-task` step 1 a command to run. This slice exposes the same facts as an **MCP server**, so any agent that supports MCP (Claude Code, Codex, Kiro, Cline and others) can ask about any allowed repo as a native tool call, without knowing script paths or flags.

The server adds no extraction. It is a thin layer over `criteria_cache`, `lookup` and the slice 3b outputs, so the CLI and the server always agree and share one cache.

## 2. Decisions (user, 2026-10-14)

1. **Tools: criteria plus status** (four tools, section 5). The guides stay skills: their value is the model-fill and lint loop, which a tool call cannot do.
2. **Which repos: explicit roots.** Repeatable `--root DIR` arguments, `PRD_MCP_ROOTS` (path-separated), or, when neither is given, the server's working directory. `--allow-any-repo` is an explicit opt-out. Any number of roots is allowed, so one server can serve many repos.
3. **Any MCP client, not one.** One stdio server, no client-specific code. Results are plain Markdown text (every client shows text) plus structured JSON where the negotiated protocol version supports it.
4. **No dependency.** The project stays stdlib-only; the small part of the MCP protocol that is needed is written by hand.
5. **Registration is the user's.** The slice ships `docs/mcp-setup.md` with snippets per client; it edits no client's configuration.

## 3. Evidence this design rests on (2026-10-14)

- `bin/prd_criteria.py` already has `lookup`, `show`, `build` over `criteria_cache.ensure/load_bank` and `lookup.select/render_*`; `criteria_cache.fingerprint/is_fresh/_read_meta` give everything `repo_status` needs, except a function that reports instead of building.
- The cache lives under `$PRD_ASSISTANT_STATE` or `~/.claude/state/prd-assistant/`, outside the repos; a build takes seconds to a few minutes and never writes into a repo.
- MCP over stdio is newline-delimited JSON-RPC 2.0 (a message never contains a raw newline). Tool results are `{"content": [...], "isError": bool}`; `structuredContent` exists from protocol version 2025-06-18; tool annotations from 2025-03-26.

## 4. Non-goals

- No tools for PRD, client guide or developer guide generation; no `prepare`/`verify`/`assemble` tools.
- No HTTP/SSE transports, no resources, no prompts, no sampling, no authentication, no progress notifications, no cancellation handling beyond ignoring the notification.
- No editing of any client's configuration, and no automatic registration.
- No concurrency: requests are handled one at a time.

## 5. The server

`bin/prd_mcp.py` is the entry point (`python3 -I bin/prd_mcp.py [--root DIR]... [--allow-any-repo] [--state-dir DIR]`). The logic lives in `prd_assistant/mcp_server.py` as pure functions so it can be tested without a process: `handle_message(msg, session, config) -> response | None`.

**Framing.** One JSON message per line on stdin; one per line on stdout, produced with `json.dumps` (no raw newlines). A line longer than 1,000,000 characters is answered with a parse error. EOF on stdin ends the process with exit 0. stdout is reserved for the protocol: during work `sys.stdout` points at stderr, and the protocol writer holds the real stdout; logs go to stderr.

**Methods.**
- `initialize`: result `{"protocolVersion", "capabilities": {"tools": {}}, "serverInfo": {"name": "prd-assistant", "version": "<TOOL_VERSION>"}, "instructions": "<fixed text>"}`. The protocol version is the client's if it is in `SUPPORTED_VERSIONS` (`2025-06-18`, `2025-03-26`, `2024-11-05`), otherwise the newest supported. The negotiated version is kept in the session.
- `notifications/initialized` and any other notification (no `id`): no response.
- `ping`: empty result.
- `tools/list`: the four tools below with `name`, `description` (fixed text, never from a repo), `inputSchema`, `annotations`.
- `tools/call`: runs the tool. An unknown tool name is a JSON-RPC error `-32602`. Argument problems (missing or wrong-typed fields, oversize strings, bad id format) and every expected failure (repo outside the roots, no CodeGraph index, facts unavailable) are **tool results with `isError: true`** and a one-paragraph message, so the model can read it and correct itself.
- Anything else: `-32601` method not found. Malformed JSON: `-32700` with `id: null`. A request that is not an object, or lacks `method`: `-32600`. A JSON array is treated as a batch and answered with an array (empty array: `-32600`).
- Every handler is wrapped: an unexpected exception becomes a tool result with `isError: true` and the exception class name (no traceback, no repo text), and is logged to stderr.

## 6. The tools

All `repo` arguments are strings (at most 4,096 characters, no NUL, `~` expanded). `structuredContent` is included only when the negotiated version is `2025-06-18` or later; the text result is always present and is the same Markdown the CLI prints.

| Tool | Arguments | Result |
|---|---|---|
| `criteria_lookup` | `repo`, `task` (string, at most 2,000 characters), `max_subjects` (integer 1 to 20, default 5), `max_candidates` (integer 1 to 200, default 60) | `lookup.render_markdown`; structured: `lookup.render_json` |
| `criteria_show` | `repo`, `id` (pattern `^C-[A-Z]+-[0-9]+$`) | `lookup.render_candidate`; structured: the candidate |
| `criteria_build` | `repo` | the same lines as `prd_criteria.py build` (cache path, commit, counts); structured: the same as an object |
| `repo_status` | `repo` | see below |

`criteria_lookup`, `criteria_show` and `criteria_build` may build or rebuild the cache (`ensure`); `criteria_build` always does. They never write into the repo. Annotations: `repo_status` has `readOnlyHint: true`; the other three have `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`; all have `openWorldHint: false`. The descriptions say "writes only its cache outside the repo".

**`repo_status`** never builds. It reports, as Markdown plus structured JSON:
- the resolved repo, whether `.codegraph/codegraph.db` exists, and whether it is a git repository;
- `cache`: `missing`, `fresh` or `stale`, with the reasons (tool version differs, commit differs, working tree differs or has N changed files, the cache is malformed, not a git repository);
- the commit and age of the facts, the CodeGraph commit it was built from, the path of the cache;
- from the cache: the slice 1 gate verdict, the dev gate verdict, route and screen counts, candidates per kind, roles read / public / undeclared / not read, request routes read, raise sites attached, screens joined to endpoints;
- a `next_step` sentence: "no index: run `codegraph init` in the repo", "no cache yet: the next lookup builds it (seconds to minutes)", "stale: the next lookup rebuilds it", or "fresh".

This needs one new function in the cache module, `criteria_cache.status(repo, state_dir) -> dict`, which reuses `fingerprint`, `is_fresh`, `_read_meta` and `_bank_ok`, and never calls `build`.

## 7. Roots and safety

- **Roots.** `--root` (repeatable), else `PRD_MCP_ROOTS` split on `os.pathsep`, else the server's working directory. Roots are resolved (`realpath`) at start-up; a root that does not exist is ignored with a warning on stderr; if no valid root remains and `--allow-any-repo` is not set, the server still starts and every tool returns an error naming the settings.
- **Checking a repo.** The argument is `expanduser`-ed and resolved (symlinks and `..` included) **before** the comparison; it must be a directory and equal to or inside one resolved root, otherwise the tool returns an error that names `--root` and `PRD_MCP_ROOTS`. With `--allow-any-repo` only the directory check applies.
- **State directory.** `--state-dir`, else `PRD_ASSISTANT_STATE`, else the default; the existing refusal of a state directory inside the repo applies.
- **Untrusted text.** Everything printed from repo text goes through the slice 4 renderers (escaped, framed as data). Tool descriptions and error messages are fixed strings; a repo path echoed in an error is passed through `scaffold.esc` and clipped to 300 characters. The output text is capped at 100,000 characters with a final line saying it was cut.
- **No ambient authority.** The server reads only the files the existing pipelines read (index copy, secret-named files and symlinks never opened) and writes only the cache.

## 8. Setup document (`docs/mcp-setup.md`)

One section per client with a registration snippet, the roots setting, and how to check it works (`tools/list` shows four tools):
- Claude Code: `claude mcp add prd-assistant -- python3 -I /home/arep/research/prd-assistant/bin/prd_mcp.py --root <dir>` and the `.mcp.json` form.
- Codex: a `[mcp_servers.prd-assistant]` table in `config.toml`.
- Cline and Kiro: an `mcpServers` entry in their MCP settings files.
- A generic block for any other client: command, arguments, environment.

Each snippet's format is checked against the client's current documentation when the slice is built; one that could not be verified is marked "unverified". The document also states the limits: one request at a time, a first build can take minutes (so call `criteria_build` once per repo, or raise the client's tool timeout), and facts reflect the files on disk at the last build.

## 9. Errors and edge cases

- A request before `initialize` is answered normally (lenient); a second `initialize` is answered again.
- `tools/call` with `arguments` missing, null or not an object: an error result, not a crash. Unknown extra arguments are ignored.
- `id` values may be numbers or strings and are echoed unchanged; `id: null` on a request is answered with `-32600`.
- A repo that exists but has no CodeGraph index, a repo whose facts fail the gate (exit 2 in the CLI) and a repo with no routes each produce an error result with the same reason text the CLI prints on stderr.
- Very long task or id strings, deeply nested JSON in arguments (parsed by `json`, rejected by type checks), emoji and bidi characters in arguments, and non-UTF-8 input bytes (replaced, not fatal).
- Two servers sharing a cache: the slice 4 atomic swap and read retry already cover it.

## 10. Testing (test-first)

- `handle_message` unit tests: every method, version negotiation (known, unknown, missing), notification silence, batches, malformed and non-object input, ids of every type, unknown method and tool, argument validation for each tool, `structuredContent` only for 2025-06-18 and later, annotations, fixed descriptions, error results never contain tracebacks.
- Roots: `--root` repeated, `PRD_MCP_ROOTS`, working-directory fallback, a missing root, symlink and `..` escapes, a repo equal to a root, a sibling directory with the root's name as a prefix (`/a/repo` vs `/a/repo-evil`), `--allow-any-repo`, `~` expansion, NUL in a path.
- `repo_status` for each cache state (missing, fresh, stale for each reason, malformed, no index, not git) using the slice 4 patched-pipeline fixtures; it never calls `build`.
- A subprocess test: start `bin/prd_mcp.py` under `-I`, drive it over pipes with `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, a bad line, then EOF; every stdout line is valid JSON with no stray output; a `print` inside a tool does not corrupt the stream; exit code 0.
- A comparison test: for one calibration repo (skipped if absent) the text of `criteria_lookup` equals the CLI's output for the same task.
- Output cap, oversize input line, hostile text in candidates (reusing the slice 4 hostile fixtures).
- A file test that `docs/mcp-setup.md` names the real script path, all four tool names and each client section.
- A fresh whole-branch review at the end.

## 11. Risks and open questions

- The MCP specification evolves; unknown future versions are answered with the newest known one and the client decides. The supported-version list is one constant.
- Client tool timeouts: a first build may exceed them; documented, and `repo_status` tells the model that a build is coming.
- Clients differ in how they pass arguments and environment; both `--root` and `PRD_MCP_ROOTS` are supported for that reason.
- `structuredContent` without an `outputSchema` is allowed; clients that validate strictly might want a schema. None is declared in this slice.

## Amendments from the slice 5 plan and calibration (2026-10-14)

1. `criteria_cache.ensure_bank` (new) builds or reuses the cache, retries the read once if a concurrent rebuild swapped it away, and validates the bank; both the CLI and the server call it.
2. `lookup.render_status` (new) prints the `repo_status` Markdown; the structured copy is the dict from `criteria_cache.status`, which never builds and never creates a directory.
3. `Session` and `Config` are small classes in `mcp_server.py`; input validation is driven by each tool's own `inputSchema`.
4. Roots precedence is `--root` values, otherwise `PRD_MCP_ROOTS`, otherwise the working directory, as specified; a working directory that is the filesystem root is not used as a default root.
5. Repo strings echoed in error messages are escaped with `scaffold.text_cell` and clipped to 300 characters.
6. All four registration snippets were checked against the clients' official documentation on 2026-10-14 (see `docs/mcp-setup.md`).
7. **Git is run with `-c core.fsmonitor=false -c core.hooksPath=/dev/null -c core.pager=cat`** so a repo's own configuration cannot make `repo_status` (or the CLI) run a command; clean/smudge filters named in the repo's config remain a documented limit.
8. **Output limits:** text is cut on a line boundary at 100,000 characters; a structured copy larger than 200,000 characters is omitted with a note; a batch holds at most 100 messages (more is `-32600`); an unexpected exception while handling a message is `-32603` and the server keeps running.
9. **Errors** echoed from the cache layer are escaped with `text_cell` like every other echoed string; a closed stdout ends the process with exit 0.
