# PRD Assistant, Slice 5: MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the slice 4 facts as an MCP server (stdio, JSON-RPC 2.0) so any MCP client can call `criteria_lookup`, `criteria_show`, `criteria_build` and `repo_status` on repos inside configured roots.

**Architecture:** `criteria_cache.status` reports a cache's state without building. `mcp_server.py` holds pure functions (`handle_message`, `handle_line`, `call_tool`, roots and repo checks, tool handlers) and a `serve` loop that works on byte streams; `bin/prd_mcp.py` is the thin process entry point. The tools reuse `criteria_cache.ensure_bank`, `lookup.select/render_*` so the CLI and the server agree and share one cache.

**Tech Stack:** Python 3.13 stdlib only. Builds on slices 1 to 4.

**Spec:** `/home/arep/research/prd-assistant/design-slice5.md` (approved 2026-10-14). Parents: `design-slice4.md`, `design-slice3b.md`, `design.md`.

## Spec deviations (decided while planning; recorded in the spec's Amendments in Task 6)

1. **`criteria_cache.ensure_bank`** (new) does what the CLI's private `_load` did (build or reuse the cache, retry once if a concurrent rebuild swapped it away, validate the bank). Both the CLI and the server call it.
2. **`lookup.render_status`** (new) prints the `repo_status` Markdown; the structured copy is the dict from `criteria_cache.status`.
3. **`Session` and `Config`** are small classes in `mcp_server.py`; input validation is driven by each tool's own `inputSchema` (one source of truth).
4. **Roots precedence:** `--root` values if any, otherwise `PRD_MCP_ROOTS`, otherwise the working directory (as in the spec; the two are not merged).

## Global Constraints

- Python stdlib only. Tests: `python3 -m unittest` (whole suite: `python3 -m unittest discover -s tests -t .`). Server: `python3 -I bin/prd_mcp.py`.
- stdout carries only protocol messages, one JSON object (or batch array) per line, produced with `json.dumps(..., ensure_ascii=True, separators=(",", ":"))`. Everything else goes to stderr.
- Tool descriptions, schemas and error messages are fixed strings. Text that comes from a repo or from an argument is passed through `scaffold.esc`, clipped, and never printed raw.
- Tool failures are results with `isError: true`; only broken requests and unknown tool names are JSON-RPC errors (`-32600`, `-32601`, `-32602`, `-32700`).
- No tool writes into a repo. `repo_status` writes nothing at all (it does not even create the state directory).
- The repo argument is resolved (`realpath`) once, checked against the resolved roots, and the resolved path is what every later step uses.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Corrupting or stalling the protocol.** Any path that writes a non-protocol byte to stdout (a `print` in a tool, a traceback), emits a message containing a raw newline, answers a notification, or leaves a request without a response (batches, ids of every type, `id: null`, oversize lines, invalid UTF-8) makes a client hang or crash.
2. **Escaping the roots.** Symlinks, `..`, a sibling whose name starts with a root's name (`/a/repo-evil` vs `/a/repo`), `~`, relative paths, NUL, and any gap between checking a path and using it.
3. **Honesty of tool metadata and results.** `readOnlyHint: true` only for `repo_status`, and `repo_status` must truly never build or create anything; tool errors must be results, not protocol errors or tracebacks; hostile text in candidates, repo names and arguments must not reach a client unescaped; `structuredContent` only when the negotiated version supports it.
4. **Resource exhaustion.** Huge lines and arguments, deeply nested JSON (`RecursionError`), repeated builds, and a stuck build blocking the stream; the output cap.
5. **Shared-cache races.** Two servers or a server and the CLI on the same cache; a cache replaced between the freshness check and the read.

---

## File structure

| File | Responsibility |
|---|---|
| `prd_assistant/criteria_cache.py` (modify) | `status`, `ensure_bank` |
| `prd_assistant/lookup.py` (modify) | `render_status` |
| `prd_assistant/mcp_server.py` (new) | protocol, tools, roots, `serve` |
| `bin/prd_mcp.py` (new) | process entry point |
| `bin/prd_criteria.py` (modify) | use `ensure_bank` |
| `docs/mcp-setup.md` (new) | per-client registration snippets |
| `tests/test_criteria_status.py`, `tests/test_mcp_protocol.py`, `tests/test_mcp_roots.py`, `tests/test_mcp_tools.py`, `tests/test_mcp_serve.py`, `tests/test_mcp_compare.py`, `tests/test_mcp_setup_doc.py` | one test file per concern |

---

### Task 1: `repo_status` data and rendering, and `ensure_bank`

**Files:**
- Modify: `prd_assistant/criteria_cache.py`, `prd_assistant/lookup.py`, `bin/prd_criteria.py`, `tests/test_criteria_cache.py` (the shared `fake_dev_prepare` also writes `dev_gate.json` and `dev_summary.json`)
- Test: `tests/test_criteria_status.py`

**Interfaces:**
- Produces:
  - `criteria_cache.status(repo, state_dir=None) -> dict` with keys `repo`, `index_present`, `git`, `cache` (`"missing"|"fresh"|"stale"`), `reasons` (list), `head`, `built_at`, `codegraph_commit`, `cache_path`, `gates` (`{"slice1","dev"}` verdict or `None`), `counts` (`{"routes","screens","candidates"}`), `coverage` (the cache's `dev/dev_summary.json` or `None`), `next_step`. Raises `EnvError` for a non-directory or a state directory inside the repo. Never calls `build`, never creates a directory.
  - `criteria_cache.ensure_bank(repo, state_dir=None, force=False) -> (cache, meta, rebuilt, bank)`
  - `lookup.render_status(status, now=None) -> str`

- [ ] **Step 1: Extend the shared test helper, then write the failing tests**

In `tests/test_criteria_cache.py` replace `fake_dev_prepare` with:

```python
def fake_dev_prepare(repo, out, today=None):
    dev = Path(out) / "dev"
    dev.mkdir(exist_ok=True)
    for name, data in (("roles.json", ROLES2), ("form_rules.json", RULES), ("error_messages.json", ERRORS),
                       ("dev_gate.json", {"verdict": "WARN", "checks": []}),
                       ("dev_summary.json", {"routes": 6, "roles": {"read": 2, "public": 0, "undeclared": 1, "not_read": 0},
                                              "requests": {"takes_input": 2, "read": 1, "not_read": 1},
                                              "messages": {"count": 3, "sites_total": 4, "sites_attached": 3},
                                              "mismatches": {"roles": 1, "rules": 1}, "screens": {"total": 1, "joined": 1},
                                              "verdict": "WARN"})):
        (dev / name).write_text(json.dumps(data))
    return {}
```

```python
# tests/test_criteria_status.py
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache, lookup
from tests.test_criteria_cache import PatchedPipeline, git, make_repo


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def build(self):
        with PatchedPipeline():
            return criteria_cache.ensure(self.repo, self.state)[0]

    def status(self):
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError("status must never build")):
            return criteria_cache.status(self.repo, self.state)

    def test_missing_cache_creates_nothing(self):
        st = self.status()
        self.assertEqual((st["cache"], st["reasons"], st["index_present"], st["git"]), ("missing", [], True, True))
        self.assertIn("builds it", st["next_step"])
        self.assertFalse(self.state.exists())

    def test_fresh_cache_reports_gates_counts_and_coverage(self):
        cache = self.build()
        st = self.status()
        self.assertEqual((st["cache"], st["reasons"]), ("fresh", []))
        self.assertEqual(st["gates"], {"slice1": "PASS", "dev": "WARN"})
        self.assertEqual(st["counts"]["routes"], 6)
        self.assertGreater(st["counts"]["candidates"]["role"], 0)
        self.assertEqual(st["coverage"]["screens"], {"total": 1, "joined": 1})
        self.assertEqual(st["cache_path"], str(cache))
        self.assertEqual(st["codegraph_commit"], "cafe123")
        self.assertEqual(st["next_step"], "The facts are fresh.")

    def test_stale_reasons(self):
        cache = self.build()
        (self.repo / "new.py").write_text("y = 1\n")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertTrue(any("working tree differs" in r for r in st["reasons"]))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        self.assertTrue(any("commit differs" in r for r in self.status()["reasons"]))
        meta = json.loads((cache / "meta.json").read_text())
        (cache / "meta.json").write_text(json.dumps({**meta, "tool_version": "0"}))
        self.assertTrue(any("tool version" in r for r in self.status()["reasons"]))

    def test_malformed_cache_files_are_stale_not_a_crash(self):
        cache = self.build()
        (cache / "criteria.json").write_text("{}")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertTrue(any("malformed" in r for r in st["reasons"]))
        (cache / "meta.json").write_text("[1]")
        st = self.status()
        self.assertEqual(st["cache"], "stale")
        self.assertIsNone(st["head"])

    def test_no_index_and_not_git(self):
        bare = make_repo(self.tmp.name, "bare", with_index=False)
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError):
            st = criteria_cache.status(bare, self.state)
        self.assertFalse(st["index_present"])
        self.assertIn("codegraph init", st["next_step"])
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError):
            self.assertFalse(criteria_cache.status(plain, self.state)["git"])

    def test_bad_inputs(self):
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.status(Path(self.tmp.name) / "nope", self.state)
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.status(self.repo, self.repo / "state")


class EnsureBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def test_returns_the_bank_and_retries_once_when_the_cache_is_swapped_away(self):
        with PatchedPipeline():
            cache, meta, rebuilt, bank = criteria_cache.ensure_bank(self.repo, self.state)
            self.assertTrue(rebuilt)
            self.assertIn("candidates", bank)
            real, calls = criteria_cache.load_bank, {"n": 0}

            def flaky(path):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise FileNotFoundError("swapped away")
                return real(path)
            with mock.patch("prd_assistant.criteria_cache.load_bank", side_effect=flaky):
                criteria_cache.ensure_bank(self.repo, self.state)
            self.assertEqual(calls["n"], 2)

    def test_a_malformed_bank_after_a_fresh_check_is_an_error(self):
        with mock.patch("prd_assistant.criteria_cache.ensure", return_value=(Path(self.tmp.name), {}, False)), \
                mock.patch("prd_assistant.criteria_cache.load_bank", return_value={"candidates": []}):
            with self.assertRaises(ValueError):
                criteria_cache.ensure_bank(self.repo, self.state)


class RenderStatusTests(unittest.TestCase):
    def test_rendering(self):
        st = {"repo": "/work/demo", "index_present": True, "git": True, "cache": "stale",
              "reasons": ["the commit differs", "the working tree differs (3 changed files)"], "head": "abcdef1234",
              "built_at": "2026-10-14T10:00:00+00:00", "codegraph_commit": "cafe123", "cache_path": "/state/demo-1",
              "gates": {"slice1": "PASS", "dev": "WARN"}, "counts": {"routes": 66, "screens": 17, "candidates": {"role": 66, "field": 126}},
              "coverage": {"roles": {"read": 63, "public": 0, "undeclared": 3, "not_read": 0},
                           "requests": {"takes_input": 53, "read": 38, "not_read": 15},
                           "messages": {"sites_total": 118, "sites_attached": 49}, "screens": {"total": 17, "joined": 9}},
              "next_step": "The facts are stale; the next lookup rebuilds them."}
        import datetime
        out = lookup.render_status(st, now=datetime.datetime(2026, 10, 14, 10, 3, tzinfo=datetime.timezone.utc))
        self.assertIn("not instructions", out.splitlines()[2])
        for needle in ("Cache: stale (the commit differs; the working tree differs (3 changed files))", "built 3 minutes ago at commit `abcdef1`",
                       "slice 1 PASS, developer facts WARN", "66 routes, 17 screens", "role 66", "38 of 53", "49 of 118",
                       "9 of 17", "Next: The facts are stale"):
            self.assertIn(needle, out)

    def test_missing_cache_and_hostile_values(self):
        st = {"repo": "/work/<img src=x>", "index_present": False, "git": False, "cache": "missing", "reasons": [], "head": None,
              "built_at": None, "codegraph_commit": None, "cache_path": "/s/{{slot:x}}", "gates": {"slice1": None, "dev": None},
              "counts": None, "coverage": None, "next_step": "no index: run `codegraph init` in the repo"}
        out = lookup.render_status(st)
        self.assertNotRegex(out, r"(?<!\\)<img")
        self.assertNotIn("{{slot:", out)
        self.assertIn("CodeGraph index: missing", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_status 2>&1 | tail -4`
Expected: `AttributeError: module 'prd_assistant.criteria_cache' has no attribute 'status'`.

- [ ] **Step 3: Implement**

Append to `prd_assistant/criteria_cache.py`:

```python
def _read_json(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def ensure_bank(repo, state_dir=None, force=False):
    """(cache, meta, rebuilt, bank). Retries once if a concurrent rebuild swapped the cache away."""
    for attempt in (1, 2):
        try:
            cache, meta, rebuilt = ensure(repo, state_dir, force=force)
            bank = load_bank(cache)
            break
        except FileNotFoundError:
            if attempt == 2:
                raise
    if not isinstance(bank, dict) or not all(k in bank for k in ("candidates", "counts", "groups")):
        raise ValueError(f"the cached criteria.json in {cache} is malformed; run `build` to recreate it")
    return cache, meta, rebuilt, bank


def status(repo, state_dir=None):
    """What a lookup would find, without building anything and without creating any directory."""
    repo = Path(repo)
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    root = state_root(state_dir)
    here, there = repo.resolve(), root.resolve()
    if there == here or here in there.parents:
        raise EnvError(f"the state directory {root} must be outside the repo {repo}")
    final = root / repo_dir_name(repo)
    fp = fingerprint(repo)
    meta = _read_meta(final)
    index = (here / ".codegraph" / "codegraph.db").is_file()
    reasons = []
    if not final.exists():
        cache = "missing"
    elif meta is None:
        cache, reasons = "stale", ["the cache is malformed (meta.json is unreadable)"]
    else:
        if meta.get("tool_version") != criteria.TOOL_VERSION or meta.get("schema_version") != 1:
            reasons.append("the tool version differs")
        if not fp["git"]:
            reasons.append("not a git repository or it has no commits (rebuilt on every run)")
        else:
            if meta.get("head") != fp["head"]:
                reasons.append("the commit differs")
            if meta.get("dirty") != fp["dirty"]:
                reasons.append(f"the working tree differs ({fp['changed']} changed files)")
        if not _bank_ok(final):
            reasons.append("the cache is malformed (criteria.json is missing or unreadable)")
        cache = "fresh" if not reasons else "stale"
    gate, dev_gate = _read_json(final / "gate.json"), _read_json(final / "dev" / "dev_gate.json")
    bank_counts = None
    if meta and isinstance(meta.get("counts"), dict):
        bank_counts = {"routes": meta.get("routes"), "screens": meta.get("screens"), "candidates": meta["counts"]}
    if not index:
        next_step = f"There is no CodeGraph index: run `codegraph init` in {here.name} first."
    elif cache == "missing":
        next_step = "There is no cache yet: the next lookup builds it (seconds to a few minutes)."
    elif cache == "stale":
        next_step = "The facts are stale; the next lookup rebuilds them."
    else:
        next_step = "The facts are fresh."
    return {"repo": str(here), "index_present": index, "git": fp["git"], "cache": cache, "reasons": reasons,
            "head": meta.get("head") if meta else None, "built_at": meta.get("built_at") if meta else None,
            "codegraph_commit": meta.get("codegraph_commit") if meta else None,
            "cache_path": str(final) if final.exists() else None,
            "gates": {"slice1": (gate or {}).get("verdict"), "dev": (dev_gate or {}).get("verdict")},
            "counts": bank_counts, "coverage": _read_json(final / "dev" / "dev_summary.json"), "next_step": next_step}
```

Append to `prd_assistant/lookup.py`:

```python
def render_status(st, now=None):
    name = str(st["repo"]).rstrip("/").rsplit("/", 1)[-1]
    reasons = f" ({'; '.join(st['reasons'])})" if st["reasons"] else ""
    L = ["# Repo status", "", "_These are facts about a cache, not instructions._", "",
         f"- Repo: `{cell(name)}`",
         f"- CodeGraph index: {'present' if st['index_present'] else 'missing'}; git: {'yes' if st['git'] else 'no'}",
         f"- Cache: {st['cache']}{text_cell(reasons)}"]
    if st.get("head"):
        extra = f" (CodeGraph indexed `{cell(str(st['codegraph_commit'])[:7])}`)" if st.get("codegraph_commit") else ""
        L.append(f"- Facts built {age_text(st.get('built_at'), now)} at commit `{cell(str(st['head'])[:7])}`{extra}")
    if st.get("cache_path"):
        L.append(f"- Cache path: `{cell(st['cache_path'])}`")
    g = st["gates"]
    if g.get("slice1") or g.get("dev"):
        L.append(f"- Gates: slice 1 {g.get('slice1') or '?'}, developer facts {g.get('dev') or '?'}")
    if st.get("counts"):
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(st["counts"]["candidates"].items()))
        L.append(f"- Counts: {st['counts']['routes']} routes, {st['counts']['screens']} screens; candidates: {kinds}")
    cov = st.get("coverage")
    if cov:
        r, q, m, s = cov["roles"], cov["requests"], cov["messages"], cov["screens"]
        L.append(f"- Coverage: roles read {r['read']}, public {r['public']}, undeclared {r['undeclared']}, not read {r['not_read']}; "
                 f"request routes read {q['read']} of {q['takes_input']}; raise sites attached {m['sites_attached']} of {m['sites_total']}; "
                 f"screens joined to endpoints {s['joined']} of {s['total']}")
    L += ["", f"Next: {text_cell(st['next_step'])}"]
    return "\n".join(L) + "\n"
```

In `bin/prd_criteria.py` replace the private loader and the retry in `main` with `ensure_bank`:

```python
def _load(args):
    return criteria_cache.ensure_bank(args.repo, args.state_dir, force=(args.command == "build"))
```
and in `main` use a single call `cache, meta, rebuilt, bank = _load(args)` (delete the inner `try/except FileNotFoundError` retry and the bank-shape check, which `ensure_bank` now owns).

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_criteria_status tests.test_criteria_cli tests.test_criteria_cache tests.test_criteria_final_review 2>&1 | tail -4`
Expected: `OK`. If a CLI test fails because it patched `criteria_cache.ensure` with a positional-only signature, keep `ensure_bank` calling `ensure(repo, state_dir, force=force)`; the CLI tests read `call_args.args[1]` for the state directory and `call_args.kwargs["force"]`.

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant bin tests
git commit -m "feat: repo status (never builds), ensure_bank, status rendering

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The protocol core (`handle_message`, tool list, validation)

**Files:**
- Create: `prd_assistant/mcp_server.py`
- Test: `tests/test_mcp_protocol.py`

**Interfaces:**
- Produces (`mcp_server.py`):
  - constants `SUPPORTED_VERSIONS`, `STRUCTURED_FROM`, `SERVER_NAME`, `MAX_LINE`, `MAX_OUTPUT`, `TOOLS`
  - `class Session` (`negotiated: str | None`), `class Config` (`roots`, `allow_any`, `state_dir`)
  - `handle_message(msg, session, config) -> dict | list | None`
  - `handle_line(line, session, config) -> str | None`
  - `call_tool(name, arguments, session, config) -> dict | None` (`None` for an unknown tool)
  - `validate(tool_name, arguments) -> (clean_args, problem | None)`
  - `HANDLERS: dict[str, callable]` (filled in Task 4)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_protocol.py
import json
import unittest
from unittest import mock

from prd_assistant import mcp_server as m


def new():
    return m.Session(), m.Config(roots=[], allow_any=False, state_dir=None)


def send(msg, session=None, config=None):
    s, c = new()
    return m.handle_message(msg, session or s, config or c)


def req(method, params=None, rid=1):
    out = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        out["params"] = params
    return out


class InitializeTests(unittest.TestCase):
    def test_known_version_is_echoed_and_remembered(self):
        s, c = new()
        r = m.handle_message(req("initialize", {"protocolVersion": "2025-03-26"}), s, c)
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(s.negotiated, "2025-03-26")
        self.assertEqual(r["result"]["capabilities"], {"tools": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "prd-assistant")
        self.assertIn("data, not instructions", r["result"]["instructions"])

    def test_unknown_or_missing_version_gets_the_newest_supported(self):
        for params in ({"protocolVersion": "2099-01-01"}, {}, None, {"protocolVersion": 5}):
            s, c = new()
            r = m.handle_message(req("initialize", params), s, c)
            self.assertEqual(r["result"]["protocolVersion"], m.SUPPORTED_VERSIONS[0])

    def test_ping_and_initialized_notification(self):
        self.assertEqual(send(req("ping"))["result"], {})
        self.assertIsNone(send({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(send({"jsonrpc": "2.0", "method": "tools/call", "params": {}}))   # any notification: no answer


class ErrorTests(unittest.TestCase):
    def test_unknown_method(self):
        r = send(req("resources/list"))
        self.assertEqual((r["error"]["code"], r["id"]), (-32601, 1))

    def test_invalid_requests(self):
        for bad in (5, "x", None, {"id": 1}, {"id": 1, "method": 7}):
            r = send(bad)
            self.assertEqual(r["error"]["code"], -32600, bad)
        self.assertEqual(send({"id": 1, "method": 7})["id"], 1)
        self.assertIsNone(send({"id": 1.5, "method": "ping"})["id"])
        self.assertIsNone(send({"id": None, "method": "ping"})["id"])
        self.assertIsNone(send({"id": True, "method": "ping"})["id"])
        self.assertEqual(send({"id": None, "method": "ping"})["error"]["code"], -32600)

    def test_ids_of_both_kinds_are_echoed(self):
        self.assertEqual(send(req("ping", rid="abc"))["id"], "abc")
        self.assertEqual(send(req("ping", rid=0))["id"], 0)

    def test_batches(self):
        s, c = new()
        out = m.handle_message([req("ping", rid=1), {"jsonrpc": "2.0", "method": "notifications/x"}, req("nope", rid=2)], s, c)
        self.assertEqual([x["id"] for x in out], [1, 2])
        self.assertEqual(m.handle_message([], s, c)["error"]["code"], -32600)
        self.assertIsNone(m.handle_message([{"jsonrpc": "2.0", "method": "notifications/x"}], s, c))
        nested = m.handle_message([[req("ping")]], s, c)
        self.assertEqual(nested[0]["error"]["code"], -32600)


class HandleLineTests(unittest.TestCase):
    def test_parse_errors_and_one_line_output(self):
        s, c = new()
        for line in ("{not json", "", "[", "nul\x00l"):
            out = json.loads(m.handle_line(line, s, c))
            self.assertEqual((out["error"]["code"], out["id"]), (-32700, None))
        out = m.handle_line(json.dumps(req("ping", rid="x y\n")), s, c)
        self.assertNotIn("\n", out)
        self.assertNotIn(" ", out)
        self.assertEqual(json.loads(out)["id"], "x y\n")

    def test_notifications_produce_no_line(self):
        s, c = new()
        self.assertIsNone(m.handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}', s, c))

    def test_pathologically_deep_json_is_a_parse_error_not_a_crash(self):
        s, c = new()
        out = json.loads(m.handle_line("[" * 200000, s, c))
        self.assertEqual(out["error"]["code"], -32700)


class ToolsListTests(unittest.TestCase):
    def test_four_tools_with_fixed_descriptions_and_honest_annotations(self):
        tools = {t["name"]: t for t in send(req("tools/list"))["result"]["tools"]}
        self.assertEqual(set(tools), {"criteria_lookup", "criteria_show", "criteria_build", "repo_status"})
        for t in tools.values():
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("repo", t["inputSchema"]["required"])
            self.assertIn("outside the repo", t["description"])
            self.assertFalse(t["annotations"]["openWorldHint"])
        self.assertTrue(tools["repo_status"]["annotations"]["readOnlyHint"])
        for name in ("criteria_lookup", "criteria_show", "criteria_build"):
            self.assertFalse(tools[name]["annotations"]["readOnlyHint"])
            self.assertFalse(tools[name]["annotations"]["destructiveHint"])
            self.assertTrue(tools[name]["annotations"]["idempotentHint"])

    def test_schemas_bound_every_input(self):
        tools = {t["name"]: t["inputSchema"]["properties"] for t in m.TOOLS}
        self.assertEqual(tools["criteria_lookup"]["task"]["maxLength"], 2000)
        self.assertEqual((tools["criteria_lookup"]["max_subjects"]["minimum"], tools["criteria_lookup"]["max_subjects"]["maximum"]), (1, 20))
        self.assertEqual(tools["criteria_lookup"]["max_candidates"]["maximum"], 200)
        self.assertIn("pattern", tools["criteria_show"]["id"])
        self.assertTrue(all(p["repo"]["maxLength"] == 4096 for p in tools.values()))


class ValidateTests(unittest.TestCase):
    def test_accepts_valid_arguments_and_drops_unknown_ones(self):
        clean, problem = m.validate("criteria_lookup", {"repo": "/r", "task": "pay", "max_subjects": 3, "extra": 1})
        self.assertIsNone(problem)
        self.assertEqual(clean, {"repo": "/r", "task": "pay", "max_subjects": 3})

    def test_rejects_with_fixed_messages_that_never_echo_the_input(self):
        hostile = "<img src=x> {{slot:a}}"
        cases = [(None, "repo"), ([], "arguments"), ({}, "repo"), ({"repo": 5}, "repo"), ({"repo": ""}, "repo"),
                 ({"repo": "x" * 5000, "task": "t"}, "repo"), ({"repo": "/r"}, "task"), ({"repo": "/r", "task": hostile * 300}, "task"),
                 ({"repo": "/r", "task": "t", "max_subjects": 0}, "max_subjects"), ({"repo": "/r", "task": "t", "max_subjects": 21}, "max_subjects"),
                 ({"repo": "/r", "task": "t", "max_subjects": True}, "max_subjects"), ({"repo": "/r", "task": "t", "max_subjects": 2.5}, "max_subjects"),
                 ({"repo": "/r", "task": "t", "max_candidates": "9"}, "max_candidates")]
        for args, word in cases:
            _, problem = m.validate("criteria_lookup", args)
            self.assertIsNotNone(problem, args)
            self.assertIn(word, problem)
            self.assertNotIn("<img", problem)
        _, problem = m.validate("criteria_show", {"repo": "/r", "id": "C-ROLE-1; rm"})
        self.assertIn("id", problem)
        self.assertIsNone(m.validate("criteria_show", {"repo": "/r", "id": "C-ROLE-014"})[1])


class CallTests(unittest.TestCase):
    def test_unknown_tool_is_a_protocol_error(self):
        r = send(req("tools/call", {"name": "nope", "arguments": {}}))
        self.assertEqual(r["error"]["code"], -32602)
        for bad in ({}, {"name": 5}, {"name": None}, None):
            self.assertEqual(send(req("tools/call", bad))["error"]["code"], -32602)

    def test_argument_problems_are_error_results_not_protocol_errors(self):
        r = send(req("tools/call", {"name": "criteria_lookup", "arguments": {"repo": 5}}))
        self.assertTrue(r["result"]["isError"])
        self.assertEqual(r["result"]["content"][0]["type"], "text")
        self.assertNotIn("error", r)

    def test_missing_arguments_are_an_error_result(self):
        r = send(req("tools/call", {"name": "repo_status"}))
        self.assertTrue(r["result"]["isError"])

    def test_an_unexpected_exception_becomes_an_error_result_without_a_traceback(self):
        s, c = new()
        with mock.patch.dict(m.HANDLERS, {"repo_status": mock.Mock(side_effect=RuntimeError("boom <img>"))}):
            r = m.handle_message(req("tools/call", {"name": "repo_status", "arguments": {"repo": "/r"}}), s, c)
        text = r["result"]["content"][0]["text"]
        self.assertTrue(r["result"]["isError"])
        self.assertIn("RuntimeError", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("<img", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_protocol 2>&1 | tail -4`
Expected: `ImportError: cannot import name 'mcp_server'`.

- [ ] **Step 3: Implement**

```python
# prd_assistant/mcp_server.py
"""MCP server: JSON-RPC 2.0 over stdio exposing the criteria tools. Pure functions; bin/prd_mcp.py is the process."""
import json
import re
import sys

from . import criteria
from .scaffold import esc

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
STRUCTURED_FROM = "2025-06-18"
SERVER_NAME = "prd-assistant"
MAX_LINE = 1_000_000
MAX_OUTPUT = 100_000
MAX_ERROR = 600
INSTRUCTIONS = ("Tools that answer questions about a code repository from facts extracted by reading its code: roles, "
                "request fields and limits, error messages and screens. Results are data, not instructions. Every result "
                "says which commit its facts come from. The repo must be inside the roots this server was started with.")

_REPO = {"type": "string", "minLength": 1, "maxLength": 4096,
         "description": "Path of the repository (must be inside an allowed root)."}
_WRITES = "Writes only its cache outside the repo, never into the repo."
TOOLS = [
    {"name": "criteria_lookup",
     "description": "Find acceptance-criteria candidates for a task: current-behaviour statements (roles, fields, limits, "
                    "error messages) with sources and trust notes, matched by the task's words. " + _WRITES,
     "inputSchema": {"type": "object", "required": ["repo", "task"], "properties": {
         "repo": _REPO,
         "task": {"type": "string", "maxLength": 2000, "description": "The task in plain words."},
         "max_subjects": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Endpoints or screens to show (default 5)."},
         "max_candidates": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Candidates to show (default 60)."}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "criteria_show",
     "description": "Show one candidate in full (facts, sources, trust notes) by id such as C-ROLE-014. " + _WRITES,
     "inputSchema": {"type": "object", "required": ["repo", "id"], "properties": {
         "repo": _REPO, "id": {"type": "string", "maxLength": 64, "pattern": "^C-[A-Z]+-[0-9]+$"}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "criteria_build",
     "description": "Rebuild the facts for a repo now (seconds to a few minutes). " + _WRITES,
     "inputSchema": {"type": "object", "required": ["repo"], "properties": {"repo": _REPO}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "repo_status",
     "description": "Say whether the facts for a repo exist and are fresh, which commit they come from, the gate verdicts and "
                    "the coverage counts. Never builds anything and writes nothing; reads only the cache outside the repo.",
     "inputSchema": {"type": "object", "required": ["repo"], "properties": {"repo": _REPO}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]
_BY_NAME = {t["name"]: t for t in TOOLS}
HANDLERS = {}      # name -> callable(args, session, config) -> result dict; filled in by the tool section


class Session:
    def __init__(self):
        self.negotiated = None


class Config:
    def __init__(self, roots, allow_any=False, state_dir=None):
        self.roots, self.allow_any, self.state_dir = list(roots), allow_any, state_dir


def _clip(text, n=MAX_ERROR):
    text = str(text)
    return text if len(text) <= n else text[:n] + "…"


def rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def error_result(message):
    return {"content": [{"type": "text", "text": _clip(message)}], "isError": True}


def _valid_id(rid):
    return isinstance(rid, (str, int)) and not isinstance(rid, bool)


def validate(tool_name, arguments):
    """(clean arguments, problem). Messages are fixed text and never echo the input."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return None, "The arguments must be an object."
    schema = _BY_NAME[tool_name]["inputSchema"]
    clean = {}
    for key, spec in schema["properties"].items():
        if key not in arguments:
            if key in schema["required"]:
                return None, f"The argument {key} is required."
            continue
        value = arguments[key]
        if spec["type"] == "string":
            if not isinstance(value, str):
                return None, f"The argument {key} must be a string."
            if len(value) < spec.get("minLength", 0) or len(value) > spec.get("maxLength", 10**9):
                return None, f"The argument {key} has an invalid length."
            if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
                return None, f"The argument {key} has an invalid format."
        else:
            if not isinstance(value, int) or isinstance(value, bool):
                return None, f"The argument {key} must be an integer."
            if value < spec["minimum"] or value > spec["maximum"]:
                return None, f"The argument {key} is out of range."
        clean[key] = value
    return clean, None


def call_tool(name, arguments, session, config):
    if name not in _BY_NAME:
        return None
    args, problem = validate(name, arguments)
    if problem:
        return error_result(problem)
    try:
        return HANDLERS[name](args, session, config)
    except ToolError as exc:
        return error_result(str(exc))
    except Exception as exc:    # a tool must never take the server down or leak a traceback
        print(f"prd-mcp: {name} failed: {type(exc).__name__}", file=sys.stderr)
        return error_result(f"The tool failed unexpectedly ({type(exc).__name__}).")


class ToolError(Exception):
    """An expected failure whose message is safe to show to a client."""


def handle_message(msg, session, config):
    if isinstance(msg, list):
        if not msg:
            return rpc_error(None, -32600, "Invalid request: empty batch.")
        out = []
        for item in msg:
            r = rpc_error(None, -32600, "Invalid request.") if isinstance(item, list) else handle_message(item, session, config)
            if r is not None:
                out.append(r)
        return out or None
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        rid = msg.get("id") if isinstance(msg, dict) and _valid_id(msg.get("id")) else None
        return rpc_error(rid, -32600, "Invalid request.")
    if "id" not in msg:
        return None
    rid = msg["id"]
    if not _valid_id(rid):
        return rpc_error(None, -32600, "Invalid request: the id must be a string or an integer.")
    method, params = msg["method"], msg.get("params")
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        session.negotiated = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": session.negotiated, "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": criteria.TOOL_VERSION}, "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return rpc_error(rid, -32602, "Invalid params: a tool name is required.")
        result = call_tool(params["name"], params.get("arguments"), session, config)
        if result is None:
            return rpc_error(rid, -32602, "Unknown tool.")
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    return rpc_error(rid, -32601, "Method not found.")


def handle_line(line, session, config):
    try:
        msg = json.loads(line)
    except (ValueError, RecursionError):
        return json.dumps(rpc_error(None, -32700, "Parse error."), ensure_ascii=True, separators=(",", ":"))
    response = handle_message(msg, session, config)
    return None if response is None else json.dumps(response, ensure_ascii=True, separators=(",", ":"))
```

(`esc` is imported for the tool section added in Task 4; leave the import in place now.)

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_protocol 2>&1 | tail -4`
Expected: `OK` (21 tests). `test_an_unexpected_exception_becomes_an_error_result_without_a_traceback` replaces `HANDLERS["repo_status"]` with a mock for the test only (`mock.patch.dict` adds the key when the dict is still empty).

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/mcp_server.py tests/test_mcp_protocol.py
git commit -m "feat: MCP protocol core (initialize, tools/list, errors, batches, argument validation)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Roots and the repo check

**Files:**
- Modify: `prd_assistant/mcp_server.py`
- Test: `tests/test_mcp_roots.py`

**Interfaces:**
- Consumes: `mcp_server.ToolError`, `scaffold.esc`.
- Produces:
  - `class RepoError(ToolError)`
  - `parse_roots(cli_roots, env_value, cwd) -> (roots: list[Path], warnings: list[str])`
  - `resolve_repo(arg, config) -> Path` (resolved, checked; raises `RepoError` with a fixed message that names `--root` and `PRD_MCP_ROOTS`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_roots.py
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import mcp_server as m


class ParseRootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a, self.b, self.c = (Path(self.tmp.name).resolve() / n for n in "abc")
        for d in (self.a, self.b, self.c):
            d.mkdir()

    def test_cli_roots_win_over_env_and_cwd(self):
        roots, warnings = m.parse_roots([str(self.a), str(self.b)], str(self.c), self.c)
        self.assertEqual((roots, warnings), ([self.a, self.b], []))

    def test_env_is_used_when_there_is_no_cli_root_and_cwd_when_there_is_neither(self):
        roots, _ = m.parse_roots([], os.pathsep.join([str(self.a), str(self.b)]), self.c)
        self.assertEqual(roots, [self.a, self.b])
        self.assertEqual(m.parse_roots([], None, self.c)[0], [self.c])
        self.assertEqual(m.parse_roots(None, "  ", self.c)[0], [self.c])

    def test_missing_and_file_roots_are_ignored_with_a_warning(self):
        f = self.a / "file.txt"
        f.write_text("x")
        roots, warnings = m.parse_roots([str(self.a), str(self.tmp.name) + "/nope", str(f)], None, self.c)
        self.assertEqual(roots, [self.a])
        self.assertEqual(len(warnings), 2)

    def test_roots_are_resolved_and_deduplicated(self):
        link = Path(self.tmp.name) / "link"
        os.symlink(self.a, link)
        self.assertEqual(m.parse_roots([str(link), str(self.a)], None, self.c)[0], [self.a])


class ResolveRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root, self.evil, self.outside = base / "root", base / "root-evil", base / "outside"
        for d in (self.root / "repo", self.evil / "repo", self.outside / "repo"):
            d.mkdir(parents=True)
        os.symlink(self.outside, self.root / "link")
        self.config = m.Config(roots=[self.root])

    def resolve(self, arg, config=None):
        return m.resolve_repo(str(arg), config or self.config)

    def test_inside_the_root_and_the_root_itself(self):
        self.assertEqual(self.resolve(self.root / "repo"), self.root / "repo")
        self.assertEqual(self.resolve(self.root), self.root)

    def test_escapes_are_rejected(self):
        for arg in (self.outside / "repo", self.evil / "repo", self.evil, self.root / "link" / "repo",
                    self.root / ".." / "outside" / "repo", self.root / "repo" / ".." / ".." / "outside"):
            with self.assertRaises(m.RepoError, msg=str(arg)):
                self.resolve(arg)

    def test_relative_paths_resolve_against_the_working_directory_then_are_checked(self):
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        self.assertEqual(self.resolve("repo"), self.root / "repo")
        os.chdir(self.outside)
        with self.assertRaises(m.RepoError):
            self.resolve("repo")

    def test_tilde_is_expanded_before_the_check(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.root)}):
            self.assertEqual(self.resolve("~/repo"), self.root / "repo")
        with mock.patch.dict(os.environ, {"HOME": str(self.outside)}):
            with self.assertRaises(m.RepoError):
                self.resolve("~/repo")

    def test_bad_values(self):
        for arg in ("repo\x00evil", str(self.root / "missing"), str(self.root / "repo" / "nope")):
            with self.assertRaises(m.RepoError):
                self.resolve(arg)
        f = self.root / "file.txt"
        f.write_text("x")
        with self.assertRaises(m.RepoError):
            self.resolve(f)

    def test_allow_any_repo_still_requires_a_directory(self):
        config = m.Config(roots=[], allow_any=True)
        self.assertEqual(self.resolve(self.outside / "repo", config), self.outside / "repo")
        with self.assertRaises(m.RepoError):
            self.resolve(self.outside / "nope", config)

    def test_no_roots_rejects_everything_and_the_message_says_how_to_fix_it(self):
        with self.assertRaises(m.RepoError) as ctx:
            self.resolve(self.root / "repo", m.Config(roots=[]))
        for needle in ("--root", "PRD_MCP_ROOTS", "--allow-any-repo"):
            self.assertIn(needle, str(ctx.exception))

    def test_the_message_escapes_and_clips_what_the_caller_typed(self):
        hostile = "<img src=x> {{slot:a}} " + "z" * 5000
        with self.assertRaises(m.RepoError) as ctx:
            self.resolve(hostile)
        text = str(ctx.exception)
        self.assertNotIn("<img", text.replace("\\<", ""))
        self.assertNotIn("{{slot:", text)
        self.assertLess(len(text), 1200)

    def test_a_symlink_swapped_in_after_the_check_does_not_matter_because_the_resolved_path_is_returned(self):
        resolved = self.resolve(self.root / "repo")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, resolved.resolve())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_roots 2>&1 | tail -4`
Expected: `AttributeError: module 'prd_assistant.mcp_server' has no attribute 'parse_roots'`.

- [ ] **Step 3: Implement** (append to `prd_assistant/mcp_server.py`; add `import os` and `from pathlib import Path` at the top)

```python
class RepoError(ToolError):
    """The repo argument cannot be used (fixed message)."""


def parse_roots(cli_roots, env_value, cwd):
    raw = list(cli_roots or [])
    if not raw and env_value:
        raw = [p for p in env_value.split(os.pathsep) if p.strip()]
    if not raw:
        raw = [str(cwd)]
    roots, warnings = [], []
    for item in raw:
        try:
            path = Path(os.path.expanduser(item)).resolve(strict=True)
        except (OSError, RuntimeError):
            warnings.append(f"prd-mcp: root {_clip(item, 200)!r} does not exist and is ignored")
            continue
        if not path.is_dir():
            warnings.append(f"prd-mcp: root {_clip(item, 200)!r} is not a directory and is ignored")
            continue
        roots.append(path)
    return list(dict.fromkeys(roots)), warnings


def resolve_repo(arg, config):
    """Resolve once (symlinks and .. included), check against the resolved roots, return the resolved path."""
    shown = esc(_clip(arg, 300))
    if "\0" in arg:
        raise RepoError("The repo path contains a NUL character.")
    try:
        path = Path(os.path.expanduser(arg)).resolve(strict=True)
    except (OSError, RuntimeError):
        raise RepoError(f"The repo {shown} does not exist or cannot be resolved.") from None
    if not path.is_dir():
        raise RepoError(f"The repo {shown} is not a directory.")
    if config.allow_any:
        return path
    for root in config.roots:
        if path == root or root in path.parents:
            return path
    raise RepoError(f"The repo {shown} is outside the allowed roots. Start the server with --root DIR (repeatable) "
                    "or set PRD_MCP_ROOTS to the folders that contain your repos, or use --allow-any-repo.")
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_roots tests.test_mcp_protocol 2>&1 | tail -4`
Expected: `OK` (13 tests in roots).

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/mcp_server.py tests/test_mcp_roots.py
git commit -m "feat: MCP roots (--root, PRD_MCP_ROOTS, working directory) and the resolved-path repo check

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The four tool handlers

**Files:**
- Modify: `prd_assistant/mcp_server.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: Tasks 1 to 3; `lookup.*`, `criteria_cache.ensure_bank/status`.
- Produces: `HANDLERS` filled for `criteria_lookup`, `criteria_show`, `criteria_build`, `repo_status`; `ok_result(text, structured, session)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_tools.py
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache, lookup
from prd_assistant import mcp_server as m
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_cache import FACTS_FULL, PatchedPipeline, make_repo
from tests.test_criteria_roles import rec


class ToolsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = make_repo(str(self.base))
        self.state = self.base / "state"
        self.config = m.Config(roots=[self.base], state_dir=str(self.state))

    def call(self, name, arguments, version="2025-06-18"):
        session = m.Session()
        m.handle_message({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": version}}, session, self.config)
        out = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
                               session, self.config)
        return out["result"]

    def text(self, result):
        return result["content"][0]["text"]


class LookupTests(ToolsBase):
    def test_lookup_builds_then_answers_with_text_and_structured_content(self):
        with PatchedPipeline() as p:
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "calculate payroll"})
            self.assertFalse(r["isError"])
            self.assertIn("not instructions", self.text(r))
            self.assertIn("[C-ROLE-001]", self.text(r))
            self.assertTrue(r["structuredContent"]["matched"])
            self.assertEqual(p.run.call_count, 1)
            self.call("criteria_lookup", {"repo": str(self.repo), "task": "calculate payroll"})
            self.assertEqual(p.run.call_count, 1)    # the second call reuses the cache

    def test_structured_content_only_for_versions_that_define_it(self):
        with PatchedPipeline():
            old = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2024-11-05")
            mid = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2025-03-26")
            new = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"}, version="2025-06-18")
        self.assertNotIn("structuredContent", old)
        self.assertNotIn("structuredContent", mid)
        self.assertIn("structuredContent", new)

    def test_caps_are_passed_through(self):
        with PatchedPipeline():
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll", "max_subjects": 1})
        self.assertEqual(len(r["structuredContent"]["subjects"]), 1)

    def test_no_match_is_a_normal_result(self):
        with PatchedPipeline():
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "xyzzy"})
        self.assertFalse(r["isError"])
        self.assertIn("No match", self.text(r))


class ShowAndBuildTests(ToolsBase):
    def test_show_found_and_not_found(self):
        with PatchedPipeline():
            ok = self.call("criteria_show", {"repo": str(self.repo), "id": "C-ROLE-001"})
            self.assertFalse(ok["isError"])
            self.assertIn("C-ROLE-001", self.text(ok))
            self.assertEqual(ok["structuredContent"]["candidate"]["id"], "C-ROLE-001")
            missing = self.call("criteria_show", {"repo": str(self.repo), "id": "C-NOPE-999"})
        self.assertTrue(missing["isError"])
        self.assertIn("criteria_lookup", self.text(missing))

    def test_build_always_rebuilds(self):
        with PatchedPipeline() as p:
            self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
            r = self.call("criteria_build", {"repo": str(self.repo)})
            self.assertEqual(p.run.call_count, 2)
        self.assertFalse(r["isError"])
        self.assertIn("candidates:", self.text(r))
        self.assertTrue(r["structuredContent"]["rebuilt"])


class StatusTests(ToolsBase):
    def test_status_never_builds_and_reports_the_state(self):
        with mock.patch("prd_assistant.criteria_cache.build", side_effect=AssertionError("must not build")):
            r = self.call("repo_status", {"repo": str(self.repo)})
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["cache"], "missing")
        self.assertIn("Cache: missing", self.text(r))
        self.assertFalse(self.state.exists())
        with PatchedPipeline():
            self.call("criteria_build", {"repo": str(self.repo)})
        r = self.call("repo_status", {"repo": str(self.repo)})
        self.assertEqual(r["structuredContent"]["cache"], "fresh")
        self.assertIn("slice 1 PASS", self.text(r))


class ErrorTests(ToolsBase):
    def test_outside_the_roots_is_an_error_result_naming_the_setting(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        for name, args in (("criteria_lookup", {"task": "x"}), ("criteria_show", {"id": "C-ROLE-001"}), ("criteria_build", {}), ("repo_status", {})):
            r = self.call(name, {"repo": str(outside), **args})
            self.assertTrue(r["isError"], name)
            self.assertIn("--root", self.text(r))

    def test_no_codegraph_index(self):
        bare = make_repo(str(self.base), "bare", with_index=False)
        r = self.call("criteria_lookup", {"repo": str(bare), "task": "x"})
        self.assertTrue(r["isError"])
        self.assertIn("CodeGraph", self.text(r))
        self.assertFalse(self.state.exists())

    def test_unavailable_facts_use_the_cli_reason(self):
        with PatchedPipeline() as p:
            p.run.return_value = (FACTS_FULL, {"verdict": "FAIL", "checks": []})
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "x"})
        self.assertTrue(r["isError"])
        self.assertIn("gate is FAIL", self.text(r))

    def test_a_repo_with_a_state_directory_inside_it_is_an_error_result(self):
        config = m.Config(roots=[self.base], state_dir=str(self.repo / "state"))
        session = m.Session()
        out = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "repo_status", "arguments": {"repo": str(self.repo)}}}, session, config)
        self.assertTrue(out["result"]["isError"])


class OutputTests(ToolsBase):
    def test_oversize_text_is_cut_with_a_note(self):
        with PatchedPipeline():
            with mock.patch("prd_assistant.lookup.render_markdown", return_value="x" * 250_000):
                r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
        text = self.text(r)
        self.assertLess(len(text), m.MAX_OUTPUT + 200)
        self.assertIn("output cut", text)

    def test_hostile_candidate_text_reaches_the_client_escaped(self):
        hostile = "<img src=x onerror=1> {{slot:a}} [x](http://e.example) ‮"
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": hostile, "via": "handler", "source": "api/c.ts:7"}]}
        bank = criteria.build_bank(FACTS, ROLES2, RULES, errors)
        meta = {"repo": "/work/demo", "head": "abcdef1", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0, "git": True}
        with mock.patch("prd_assistant.criteria_cache.ensure_bank", return_value=(Path("/c"), meta, False, bank)):
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll calculate"})
            s = self.call("criteria_show", {"repo": str(self.repo), "id": next(c["id"] for c in bank["candidates"] if c["kind"] == "error")})
        for result in (r, s):
            text = self.text(result)
            self.assertNotRegex(text, r"(?<!\\)<img")
            self.assertNotIn("{{slot:", text)
            self.assertNotIn("‮", text)

    def test_unexpected_errors_in_the_cache_layer_are_error_results(self):
        with mock.patch("prd_assistant.criteria_cache.ensure_bank", side_effect=KeyError("candidates")):
            r = self.call("criteria_lookup", {"repo": str(self.repo), "task": "payroll"})
        self.assertTrue(r["isError"])
        self.assertNotIn("Traceback", self.text(r))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_tools 2>&1 | tail -4`
Expected: failures with `KeyError: 'criteria_lookup'` (no handlers yet).

- [ ] **Step 3: Implement** (append to `prd_assistant/mcp_server.py`; add `from . import criteria_cache, lookup` to the imports)

```python
def ok_result(text, structured, session):
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n\n[output cut at {MAX_OUTPUT} characters]\n"
    result = {"content": [{"type": "text", "text": text}], "isError": False}
    if structured is not None and session.negotiated and session.negotiated >= STRUCTURED_FROM:
        result["structuredContent"] = structured
    return result


def _info(meta, cache):
    return {"repo": meta.get("repo"), "head": meta.get("head"), "built_at": meta.get("built_at"),
            "changed": meta.get("changed"), "git": meta.get("git"), "cache": str(cache)}


def _failure(exc):
    return ToolError(_clip(esc(str(exc))))


def _bank(args, config, force=False):
    repo = resolve_repo(args["repo"], config)
    try:
        return criteria_cache.ensure_bank(repo, config.state_dir, force=force)
    except criteria_cache.FactsUnavailable as exc:
        raise _failure(exc) from None
    except (criteria_cache.EnvError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise _failure(exc) from None


def _criteria_lookup(args, session, config):
    cache, meta, _, bank = _bank(args, config)
    info = _info(meta, cache)
    sel = lookup.select(bank, args["task"], args.get("max_subjects", 5), args.get("max_candidates", 60))
    return ok_result(lookup.render_markdown(sel, info, bank), lookup.render_json(sel, info), session)


def _criteria_show(args, session, config):
    cache, meta, _, bank = _bank(args, config)
    candidate = lookup.find_candidate(bank, args["id"])
    if candidate is None:
        raise ToolError("No candidate with that id exists in the current facts (ids change when the code changes). "
                        "Run criteria_lookup to see the current ids.")
    info = _info(meta, cache)
    return ok_result(lookup.render_candidate(candidate, info), {"meta": info, "candidate": candidate}, session)


def _criteria_build(args, session, config):
    cache, meta, rebuilt, bank = _bank(args, config, force=True)
    counts = ", ".join(f"{k}: {v}" for k, v in sorted(bank["counts"].items()))
    text = f"cache: {cache}\ncommit: {str(meta.get('head') or '?')[:7]}\ncandidates: {counts}\n"
    return ok_result(text, {"cache": str(cache), "commit": meta.get("head"), "counts": bank["counts"], "rebuilt": rebuilt}, session)


def _repo_status(args, session, config):
    repo = resolve_repo(args["repo"], config)
    try:
        st = criteria_cache.status(repo, config.state_dir)
    except criteria_cache.EnvError as exc:
        raise _failure(exc) from None
    return ok_result(lookup.render_status(st), st, session)


HANDLERS.update({"criteria_lookup": _criteria_lookup, "criteria_show": _criteria_show,
                 "criteria_build": _criteria_build, "repo_status": _repo_status})
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_tools tests.test_mcp_protocol tests.test_mcp_roots 2>&1 | tail -4`
Expected: `OK`. If the hostile-text test fails because `render_candidate` prints the facts, the Slice 4 fix (one escaped `key: value` line per fact) already covers it; check `lookup.render_candidate`.

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/mcp_server.py tests/test_mcp_tools.py
git commit -m "feat: MCP tool handlers (criteria_lookup, criteria_show, criteria_build, repo_status)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The stdio loop and `bin/prd_mcp.py`

**Files:**
- Modify: `prd_assistant/mcp_server.py` (add `serve`)
- Create: `bin/prd_mcp.py`
- Test: `tests/test_mcp_serve.py`

**Interfaces:**
- Produces: `serve(stdin, stdout, config) -> int` (byte streams); CLI `prd_mcp.py [--root DIR]... [--allow-any-repo] [--state-dir DIR]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_serve.py
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import mcp_server as m
from tests.test_criteria_cache import make_repo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "prd_mcp.py"


def lines(*msgs):
    return b"".join(x if isinstance(x, bytes) else (x if isinstance(x, str) else json.dumps(x)).encode() + b"\n" for x in msgs)


def run_serve(data, config=None, stderr=None):
    out = io.BytesIO()
    with contextlib.redirect_stderr(stderr or io.StringIO()):
        code = m.serve(io.BytesIO(data), out, config or m.Config(roots=[]))
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def req(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})}


class ServeTests(unittest.TestCase):
    def test_a_conversation(self):
        data = lines(req("initialize", {"protocolVersion": "2025-06-18"}, 1),
                     {"jsonrpc": "2.0", "method": "notifications/initialized"}, req("tools/list", None, 2), "", req("ping", None, 3))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual([o["id"] for o in out], [1, 2, 3])
        self.assertEqual(len(out[1]["result"]["tools"]), 4)

    def test_blank_lines_bad_lines_and_invalid_utf8_do_not_stop_the_stream(self):
        data = lines("not json", b"\xff\xfe broken \xc3\n", req("ping", None, 7))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual([o.get("id") for o in out], [None, None, 7])
        self.assertEqual(out[0]["error"]["code"], -32700)

    def test_an_oversize_line_is_one_parse_error_and_the_next_message_still_works(self):
        data = b"x" * (m.MAX_LINE + 500) + b"\n" + lines(req("ping", None, 9))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertIn("long", out[0]["error"]["message"])
        self.assertEqual(out[1]["id"], 9)

    def test_a_line_without_a_final_newline_is_still_answered(self):
        code, out = run_serve(json.dumps(req("ping", None, 4)).encode())
        self.assertEqual(out[0]["id"], 4)

    def test_a_closed_stdout_ends_the_loop_quietly(self):
        class Broken:
            def write(self, b):
                raise BrokenPipeError

            def flush(self):
                raise BrokenPipeError
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.serve(io.BytesIO(lines(req("ping"))), Broken(), m.Config(roots=[])), 0)

    def test_a_print_inside_a_tool_goes_to_stderr_not_into_the_protocol(self):
        def noisy(args, session, config):
            print("stray output that would corrupt the stream")
            return m.ok_result("fine", None, session)
        err = io.StringIO()
        with mock.patch.dict(m.HANDLERS, {"repo_status": noisy}):
            code, out = run_serve(lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": "/r"}}, 5)), stderr=err)
        self.assertEqual(out[0]["result"]["content"][0]["text"], "fine")
        self.assertIn("stray output", err.getvalue())

    def test_output_lines_never_contain_raw_newlines_or_non_ascii(self):
        out = io.BytesIO()
        with contextlib.redirect_stderr(io.StringIO()):
            m.serve(io.BytesIO(lines(req("ping", None, "id- -\n-‮"))), out, m.Config(roots=[]))
        raw = out.getvalue()
        self.assertEqual(raw.count(b"\n"), 1)
        raw.decode("ascii")


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = make_repo(str(self.base), with_index=False)

    def run_script(self, data, *args):
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], input=data, capture_output=True, timeout=60)
        return run, [json.loads(line) for line in run.stdout.splitlines()]

    def test_end_to_end_over_pipes(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        data = lines(req("initialize", {"protocolVersion": "2025-06-18"}, 1), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     req("tools/list", None, 2),
                     req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 3),
                     req("tools/call", {"name": "repo_status", "arguments": {"repo": str(outside)}}, 4),
                     "garbage line", req("ping", None, 5))
        run, out = self.run_script(data, "--root", str(self.base), "--state-dir", str(self.base / "state"))
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        by_id = {o.get("id"): o for o in out}
        self.assertEqual(len(by_id[2]["result"]["tools"]), 4)
        self.assertFalse(by_id[3]["result"]["isError"])
        self.assertIn("codegraph init", by_id[3]["result"]["content"][0]["text"])
        self.assertTrue(by_id[4]["result"]["isError"])
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(by_id[5]["result"], {})
        self.assertFalse((self.base / "state").exists())

    def test_roots_from_the_environment_and_the_working_directory(self):
        data = lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 1))
        env_run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--state-dir", str(self.base / "s")], input=data, capture_output=True,
                                 timeout=60, env={"PRD_MCP_ROOTS": str(self.base), "PATH": "/usr/bin:/bin"}, cwd="/")
        self.assertFalse(json.loads(env_run.stdout)["result"]["isError"])
        cwd_run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--state-dir", str(self.base / "s")], input=data, capture_output=True,
                                 timeout=60, env={"PATH": "/usr/bin:/bin"}, cwd=str(self.base))
        self.assertFalse(json.loads(cwd_run.stdout)["result"]["isError"])
        nowhere = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=data, capture_output=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin"}, cwd="/")
        self.assertTrue(json.loads(nowhere.stdout)["result"]["isError"])

    def test_allow_any_repo_and_warnings_on_stderr(self):
        data = lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 1))
        run, out = self.run_script(data, "--root", str(self.base / "missing"), "--allow-any-repo", "--state-dir", str(self.base / "s"))
        self.assertFalse(out[0]["result"]["isError"])
        self.assertIn("does not exist", run.stderr.decode())
        self.assertNotIn("does not exist", run.stdout.decode())

    def test_help(self):
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertIn("--root", run.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify RED**

Run: `cd /home/arep/research/prd-assistant && python3 -m unittest tests.test_mcp_serve 2>&1 | tail -4`
Expected: `AttributeError: module 'prd_assistant.mcp_server' has no attribute 'serve'`.

- [ ] **Step 3: Implement**

Append to `prd_assistant/mcp_server.py` (add `import contextlib` at the top):

```python
def serve(stdin, stdout, config):
    """Read newline-delimited JSON-RPC from a binary stream, answer on another. stdout stays protocol-only."""
    session = Session()
    with contextlib.redirect_stdout(sys.stderr):      # a stray print can never corrupt the protocol stream
        while True:
            raw = stdin.readline(MAX_LINE + 1)
            if not raw:
                return 0
            if len(raw) > MAX_LINE and not raw.endswith(b"\n"):
                while True:                           # drop the rest of the oversize line
                    chunk = stdin.readline(65536)
                    if not chunk or chunk.endswith(b"\n"):
                        break
                out = json.dumps(rpc_error(None, -32700, "Message too long."), separators=(",", ":"))
            else:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                out = handle_line(line, session, config)
            if out is None:
                continue
            try:
                stdout.write(out.encode("ascii") + b"\n")
                stdout.flush()
            except (BrokenPipeError, ValueError):
                return 0
```

```python
#!/usr/bin/env python3
"""MCP server (stdio) exposing the criteria tools: criteria_lookup, criteria_show, criteria_build, repo_status.

Usage:
  python3 -I bin/prd_mcp.py [--root DIR]... [--allow-any-repo] [--state-dir DIR]
Roots: repeatable --root, else the PRD_MCP_ROOTS environment variable (path-separated), else the working directory.
Only repos inside a root can be queried; --allow-any-repo lifts that. Facts are cached outside the repos
(--state-dir, PRD_ASSISTANT_STATE, or ~/.claude/state/prd-assistant/). stdout carries only protocol messages.
"""
import argparse
import os
import sys
from pathlib import Path

# -I removes the script directory from sys.path; add the (trusted) project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_assistant import mcp_server  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", default=[], help="a folder whose repos may be queried (repeatable)")
    parser.add_argument("--allow-any-repo", action="store_true", help="do not restrict the repos that can be queried")
    parser.add_argument("--state-dir", help="where the facts are cached")
    args = parser.parse_args(argv)
    roots, warnings = mcp_server.parse_roots(args.root, os.environ.get("PRD_MCP_ROOTS"), Path.cwd())
    for warning in warnings:
        print(warning, file=sys.stderr)
    if not roots and not args.allow_any_repo:
        print("prd-mcp: no usable root; every tool will answer with an error. Use --root DIR or PRD_MCP_ROOTS.", file=sys.stderr)
    config = mcp_server.Config(roots, args.allow_any_repo, args.state_dir)
    return mcp_server.serve(sys.stdin.buffer, sys.stdout.buffer, config)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify GREEN**

Run: `cd /home/arep/research/prd-assistant && chmod +x bin/prd_mcp.py && python3 -m unittest tests.test_mcp_serve 2>&1 | tail -4`
Expected: `OK` (11 tests). The environment passed to the subprocess in `test_roots_from_the_environment...` has no `PYTHONPATH`; the script adds the project root itself.

- [ ] **Step 5: Whole suite and commit**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add prd_assistant/mcp_server.py bin/prd_mcp.py tests/test_mcp_serve.py
git commit -m "feat: MCP stdio loop and bin/prd_mcp.py entry point

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Setup document, real-repo checks, hardening, notes and spec amendments

**Files:**
- Create: `docs/mcp-setup.md`, `tests/test_mcp_setup_doc.py`, `tests/test_mcp_compare.py`, `tests/test_mcp_hardening.py`
- Modify: `docs/calibration-notes.md`, `design-slice5.md` (Amendments)

**Interfaces:**
- Consumes: everything above.
- Produces: the setup document with per-client snippets (each marked verified or unverified), the recorded real-repo session, golden comparison test, hardening tests, spec amendments.

- [ ] **Step 1: Hardening tests (inputs the earlier tasks do not cover) and run them**

```python
# tests/test_mcp_hardening.py
import json
import time
import unittest

from prd_assistant import mcp_server as m


def call(msg):
    s, c = m.Session(), m.Config(roots=[])
    return m.handle_line(msg if isinstance(msg, str) else json.dumps(msg), s, c)


class HostileInputTests(unittest.TestCase):
    def test_deeply_nested_arguments_and_huge_strings_are_harmless(self):
        nested = "[" * 5000 + "]" * 5000
        line = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"criteria_lookup","arguments":{"repo":"/r","task":"t","x":' + nested + '}}}'
        started = time.monotonic()
        out = json.loads(call(line))
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("result", out)
        huge = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "criteria_lookup", "arguments": {"repo": "/r", "task": "a" * 1_000_000}}}
        out = json.loads(call(huge))
        self.assertTrue(out["result"]["isError"])

    def test_every_method_name_and_params_type_is_survived(self):
        for params in (None, 5, "x", [], {}, {"name": []}, {"name": "criteria_lookup", "arguments": "not an object"}):
            for method in ("initialize", "ping", "tools/list", "tools/call", "x" * 10000, ""):
                out = call({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                self.assertIsNotNone(out)
                json.loads(out)

    def test_unknown_tool_error_does_not_echo_the_name(self):
        out = json.loads(call({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "<img src=x> {{slot:a}}", "arguments": {}}}))
        self.assertEqual(out["error"]["code"], -32602)
        self.assertNotIn("<img", json.dumps(out))

    def test_descriptions_and_schemas_contain_no_repo_text_and_are_stable(self):
        a, b = json.dumps(m.TOOLS, sort_keys=True), json.dumps(m.TOOLS, sort_keys=True)
        self.assertEqual(a, b)
        self.assertNotIn("/home/", a)


if __name__ == "__main__":
    unittest.main()
```

Run: `cd /home/arep/research/prd-assistant && timeout 300 python3 -m unittest tests.test_mcp_hardening 2>&1 | tail -6`
Expected: these exercise behaviour built in Tasks 2 to 5, so they may already pass. **Every one that fails or times out is a real defect:** keep the test, find the cause, fix the code, rerun, then run the whole suite, and record the fix in the ledger.

- [ ] **Step 2: Write the setup document test (RED first), then the document**

```python
# tests/test_mcp_setup_doc.py
import unittest
from pathlib import Path

from prd_assistant import mcp_server

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "mcp-setup.md"


class SetupDocTests(unittest.TestCase):
    def test_names_the_real_script_every_tool_every_client_and_the_settings(self):
        text = DOC.read_text()
        self.assertTrue((ROOT / "bin" / "prd_mcp.py").is_file())
        for needle in ("/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "PRD_MCP_ROOTS", "--allow-any-repo",
                       "Claude Code", "Codex", "Cline", "Kiro", "mcpServers", "mcp_servers", "one request at a time"):
            self.assertIn(needle, text)
        for tool in mcp_server.TOOLS:
            self.assertIn(tool["name"], text)

    def test_every_snippet_says_whether_it_was_checked(self):
        text = DOC.read_text()
        for client in ("Claude Code", "Codex", "Cline", "Kiro"):
            section = text.split(f"## {client}", 1)[1].split("\n## ", 1)[0]
            self.assertTrue("Status: checked against" in section or "Status: unverified" in section, client)


if __name__ == "__main__":
    unittest.main()
```

Run `python3 -m unittest tests.test_mcp_setup_doc 2>&1 | tail -3` (Expected: `FileNotFoundError`). Then **verify each client's current registration format** with WebSearch/WebFetch (Claude Code `claude mcp add` and `.mcp.json`; Codex `config.toml` `[mcp_servers.<name>]`; Cline `cline_mcp_settings.json`; Kiro `.kiro/settings/mcp.json`), and write `docs/mcp-setup.md` with these sections. For each client, replace the `Status:` line with `Status: checked against <source and date>` if you confirmed the snippet, otherwise leave `Status: unverified` and say what was uncertain:

````markdown
# Using the PRD assistant as an MCP server

The server (`bin/prd_mcp.py`) speaks MCP over stdio, so any client that can run an MCP server can use it. It offers four tools: `criteria_lookup`, `criteria_show`, `criteria_build` and `repo_status`. It reads the repos you allow and writes only its cache (`~/.claude/state/prd-assistant/` or `--state-dir`), never into a repo. These snippets are for you to add to your own configuration; nothing here edits a client for you.

## Which repos it may read

Give it the folders that contain your repos: repeat `--root DIR`, or set `PRD_MCP_ROOTS` (several folders separated by `:`). With neither, it uses its working directory, which not every client sets to your project. `--allow-any-repo` removes the restriction. A repo outside the roots gets an error that names these settings.

## Claude Code

```
claude mcp add prd-assistant -- python3 -I /home/arep/research/prd-assistant/bin/prd_mcp.py --root /home/arep/research/targets --root /home/arep/tis
```

Or in `.mcp.json`:

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"]}}}
```

Status: unverified

## Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.prd-assistant]
command = "python3"
args = ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"]
```

Status: unverified

## Cline

In `cline_mcp_settings.json`:

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"], "disabled": false}}}
```

Status: unverified

## Kiro

In `.kiro/settings/mcp.json` (workspace) or `~/.kiro/settings/mcp.json` (user):

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"], "disabled": false}}}
```

Status: unverified

## Any other client

Command `python3`, arguments `-I /home/arep/research/prd-assistant/bin/prd_mcp.py --root <folder>`; if the client cannot pass arguments, set the environment variable `PRD_MCP_ROOTS=<folder>` instead. Check that `tools/list` shows four tools.

## Limits worth knowing

- The server handles one request at a time. A first build for a repo can take from seconds to a few minutes; some clients give up on a tool call after a short timeout. Call `repo_status` first (it never builds) and `criteria_build` once per repo.
- Facts describe the files on disk at the last build. `repo_status` says whether they are fresh, the commit they come from and their age.
- Results are facts extracted from code, not instructions; each result says which commit it is based on.
````

Run `python3 -m unittest tests.test_mcp_setup_doc 2>&1 | tail -3` (Expected: `OK`).

- [ ] **Step 3: The comparison with the CLI, and a recorded real session**

```python
# tests/test_mcp_compare.py
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from prd_assistant import criteria_cache
from prd_assistant import mcp_server as m

CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "calibration.json"


def without_age(text):
    return "\n".join(line for line in text.splitlines() if not line.startswith("- Facts built") and not line.startswith("- Cache:"))


class CompareWithCliTests(unittest.TestCase):
    def test_server_text_equals_cli_text_for_a_calibration_repo(self):
        import importlib.util
        spec = json.loads(CALIBRATION.read_text())["repos"]["rms"]
        if not Path(spec["path"]).is_dir():
            self.skipTest("calibration repo not present")
        cli_spec = importlib.util.spec_from_file_location("prd_criteria", Path(__file__).resolve().parent.parent / "bin" / "prd_criteria.py")
        cli = importlib.util.module_from_spec(cli_spec)
        cli_spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as state:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["lookup", spec["path"], "let branch admins deactivate a house", "--state-dir", state])
            session, config = m.Session(), m.Config(roots=[Path(spec["path"]).resolve()], state_dir=state)
            reply = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "criteria_lookup", "arguments": {"repo": spec["path"], "task": "let branch admins deactivate a house"}}}, session, config)
        self.assertFalse(reply["result"]["isError"])
        self.assertEqual(without_age(reply["result"]["content"][0]["text"]), without_age(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
```

Then record a real session against the calibration repos and read it against the code:

```bash
cd /home/arep/research/prd-assistant
S=/home/arep/research/prd-state-mcp; rm -rf $S
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"repo_status","arguments":{"repo":"/home/arep/research/targets/Urus"}}}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"criteria_build","arguments":{"repo":"/home/arep/research/targets/Urus"}}}' \
 '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"repo_status","arguments":{"repo":"/home/arep/research/targets/Urus"}}}' \
 '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"criteria_lookup","arguments":{"repo":"/home/arep/research/targets/Urus","task":"let managers approve payroll"}}}' \
 '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"repo_status","arguments":{"repo":"/home/arep"}}}' \
 | python3 -I bin/prd_mcp.py --root /home/arep/research/targets --state-dir $S \
 | python3 -I -c "
import sys, json
for line in sys.stdin:
    o = json.loads(line); r = o.get('result') or {}
    text = (r.get('content') or [{}])[0].get('text', '')
    print(o['id'], 'ERROR' if r.get('isError') else 'ok', '|', text.replace(chr(10), ' / ')[:230])"
```
Expected: id 2 says the cache is missing and nothing was created; id 3 builds; id 4 says fresh with gate verdicts and counts; id 5 lists `POST /api/v1/payroll/:id/approve` with `FINANCE, ADMIN` and `MANAGER` as derived; id 6 is an error naming `--root`. Anything else is a defect: write a failing test, fix, rerun, and record it.

- [ ] **Step 4: Notes and spec amendments**

Append `## Slice 5 (MCP server)` to `docs/calibration-notes.md`: the command, the recorded session (what each call returned), the comparison test, the client snippets and which were verified, and the limits (one request at a time, first-build timeouts, facts as of the last build). Append `## Amendments from the slice 5 plan and calibration (<date>)` to `design-slice5.md` listing the four deviations in this plan's header and every decision recorded in the ledger.

- [ ] **Step 5: Whole suite, commit, task-done**

```bash
cd /home/arep/research/prd-assistant && python3 -m unittest discover -s tests -t . 2>&1 | tail -3
git add -A bin prd_assistant tests docs design-slice5.md && git commit -m "feat: MCP setup document, hardening tests, comparison with the CLI, notes and spec amendments

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Then run `task-done` for Task 6 with the whole-suite command.

---

## Final review (after Task 6)

Follow `executing-plans` "Final Review": build the package with `review-package plans/2026-10-14-slice5-mcp-server.md <MERGE_BASE> HEAD` (MERGE_BASE is the commit the slice 5 branch was cut from, `bfe946a`, recorded in the ledger at setup), dispatch one fresh reviewer on the most capable model, read-only and without sub-subagents, with this plan's Review Focus verbatim plus: the exact JSON-RPC and MCP behaviours against the specification (initialize, notifications, errors, batches, `isError` versus protocol errors), stdout discipline, the roots check against races and symlinks, and performance; re-grade by effect; fix Critical and Important findings in one pass (each RED then GREEN, suite green); ledger minors as `Final: minor (deferred)` and declined-to-judge items as `Final: Ruling:`; delete the plan workspace; end with the lists "Rulings I made" and "Deferred minors" and a `result:` line. The repo is a standalone local project; no interactive branch-finishing step.
