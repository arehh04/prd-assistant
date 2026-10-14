# Using the PRD assistant as an MCP server

The server (`bin/prd_mcp.py`) speaks MCP over stdio, so any client that can run an MCP server can use it. It offers four tools: `criteria_lookup`, `criteria_show`, `criteria_build` and `repo_status`. It reads the repos you allow and writes only its cache (`~/.claude/state/prd-assistant/`, or `--state-dir`), never into a repo. These snippets are for you to add to your own configuration; nothing here edits a client for you.

## Which repos it may read

Give it the folders that contain your repos: repeat `--root DIR`, or set `PRD_MCP_ROOTS` (several folders separated by `:`). With neither, it uses its working directory, which not every client sets to your project (a working directory of `/` is never used). `--allow-any-repo` removes the restriction. A repo outside the roots gets an error that names these settings.

## Claude Code

```
claude mcp add prd-assistant -- python3 -I /home/arep/research/prd-assistant/bin/prd_mcp.py --root /home/arep/research/targets --root /home/arep/tis
```

Everything after `--` is the server command; Claude Code's own options (`--scope`, `--env`, `--transport`) go before the server name. Or write it in `.mcp.json` at the project root:

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"]}}}
```

Check it with `claude mcp list` or `/mcp` inside a session.

Status: checked against https://code.claude.com/docs/en/mcp on 2026-10-14

## Codex

In `~/.codex/config.toml` (or `.codex/config.toml` in a trusted project):

```toml
[mcp_servers.prd-assistant]
command = "python3"
args = ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"]
```

Codex also accepts `cwd` and an `env` table for a server, and `codex mcp add prd-assistant -- python3 -I <script> --root <dir>` writes the same entry.

Status: checked against https://learn.chatgpt.com/docs/extend/mcp (the page https://developers.openai.com/codex/mcp redirects there) on 2026-10-14

## Cline

In `cline_mcp_settings.json` (the extension opens it from the MCP Servers icon, Configure tab, "Configure MCP Servers"; the CLI keeps it in `~/.cline/data/settings/`):

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"], "disabled": false, "autoApprove": []}}}
```

Status: checked against https://docs.cline.bot/mcp/configuring-mcp-servers on 2026-10-14

## Kiro

In `.kiro/settings/mcp.json` (this workspace) or `~/.kiro/settings/mcp.json` (all workspaces; the workspace file wins when both exist):

```json
{"mcpServers": {"prd-assistant": {"command": "python3", "args": ["-I", "/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "/path/to/your/repos"], "disabled": false}}}
```

Status: checked against https://kiro.dev/docs/mcp/configuration/ on 2026-10-14

## Any other client

Command `python3`, arguments `-I /home/arep/research/prd-assistant/bin/prd_mcp.py --root <folder>`. If the client cannot pass arguments, set the environment variable `PRD_MCP_ROOTS=<folder>` instead. Check that `tools/list` shows four tools.

## Limits worth knowing

- The server handles one request at a time. A first build for a repo can take from seconds to a few minutes; some clients give up on a tool call after a short timeout. Call `repo_status` first (it never builds) and `criteria_build` once per repo.
- Facts describe the files on disk at the last build. `repo_status` says whether they are fresh, the commit they come from and their age.
- Results are facts extracted from code, not instructions; each result says which commit it is based on.
- A repo needs a CodeGraph index (`codegraph init` in the repo); the server never creates one.
