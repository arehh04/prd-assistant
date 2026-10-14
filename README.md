# PRD Assistant

Reads a code repo and writes documents about it. Scripts pull every table, count and label from
the code. A model only writes short sentences, and those are checked against the code. Before
anything is built, a **trust gate** compares the facts with a separate count from the source. If
they do not match, it stops.

What you can make:

| Output | How | For |
|---|---|---|
| `facts.json` and a gate result | `bin/prd_facts.py` | the base for all the rest |
| Draft PRD | `bin/prd_draft.py`, skill `prd-from-code` | new people joining a project |
| Client guide ("how to use it") | `bin/prd_draft.py guide-prepare`, skill `client-guide-from-code` | end users |
| Developer guide (roles, fields, errors, front/back mismatches) | `bin/prd_draft.py dev-prepare`, skill `developer-guide-from-code` | developers |
| Acceptance-criteria ideas | `bin/prd_criteria.py` or the MCP server | step 1 of `team-task` |

## What you need

- Python 3 (built on 3.13). No extra packages.
- The CodeGraph command on your `PATH`. The repo you study needs a `.codegraph/` index (run
  `codegraph init` inside it). If it has none, `prd_facts.py` indexes a safe copy and never
  writes to your repo.
- Optional: Claude Code, to use the skills in `skills/` and the agent in `agents/`.

Run the scripts with `python3 -I`. It keeps Python from loading stray files.

## Quick start

```bash
git clone https://github.com/arehh04/prd-assistant.git
cd prd-assistant
python3 -m unittest discover -s tests -t . -v     # check that it works

# step 1: get the facts and run the gate
python3 -I bin/prd_facts.py /path/to/repo --out /path/to/output
```

Exit codes: `0` pass or warning, `2` fail (do not build documents from these facts), `3` setup or
index problem. `--no-adapters` skips the Laravel route reader. If you leave out `--out`, files go
to `~/prd-out/<repo>-<date>`. Keep the output folder outside the repo you study.

## Draft PRD

```bash
python3 -I bin/prd_draft.py prepare REPO --out OUT   # facts, gate, and slots.template.json
# fill in the text slots (the prd-writer agent does this)
python3 -I bin/prd_draft.py verify   --out OUT       # check the text against the code
python3 -I bin/prd_draft.py assemble --out OUT       # build the final document
```

The guides work the same way. Use `guide-prepare` (writes `OUT/guide/`) or `dev-prepare` (writes
`OUT/dev/`) instead of `prepare`. Exit codes: `0` ok, `1` check failed, `2` gate failed, `3` setup
or input problem.

The easy way is Claude Code. Copy the folders in `skills/` to `~/.claude/skills/` and
`agents/prd-writer.md` to `~/.claude/agents/`. Then ask for "a draft PRD of this repo", "a client
guide" or "a developer guide". The skill files point to `/home/arep/research/prd-assistant`. Change
that path if you cloned the repo somewhere else.

## Acceptance-criteria ideas

Shows what the code does today for a task (for example "this endpoint only allows role X"), so
your criteria start from real behaviour.

```bash
python3 -I bin/prd_criteria.py build  REPO                          # build or refresh the facts
python3 -I bin/prd_criteria.py lookup REPO "add refund approval"    # ideas for a task
python3 -I bin/prd_criteria.py show   REPO --id C-ROLE-014          # one idea in full
```

Add `--json` for machine-readable output. Use `--max-subjects` and `--max-candidates` to limit
results. Facts are saved in `~/.claude/state/prd-assistant/` (change it with `--state-dir`) and
rebuilt when the repo changes. Exit codes: `0` ok (also when nothing matches), `2` no facts, `3`
setup or input problem. Treat these as evidence, not as final requirements. See
`docs/team-task-step1-criteria.md` for how `team-task` uses them.

## MCP server

`bin/prd_mcp.py` gives other tools four actions over stdio: `criteria_lookup`, `criteria_show`,
`criteria_build` and `repo_status`.

```bash
claude mcp add prd-assistant -- python3 -I /full/path/to/prd-assistant/bin/prd_mcp.py --root /path/to/your/repos
```

It only reads repos inside a `--root` (or inside `PRD_MCP_ROOTS`). Setup for Claude Code, Codex,
Cline and Kiro is in [`docs/mcp-setup.md`](docs/mcp-setup.md).

## What is in the repo

```
bin/             the commands you run (prd_facts, prd_draft, prd_criteria, prd_mcp)
prd_assistant/   the code behind them
skills/          Claude Code skills (prd-from-code, client-guide-from-code, developer-guide-from-code)
agents/          prd-writer agent (fills the text slots, read-only)
calibration/     expected counts used by the tests
docs/            MCP setup, calibration notes, team-task link
design*.md       how each part was designed; plans/ has the build plans
tests/           the test suite
```

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

## Good to know

- Facts match the files at the time of the last build. Check the commit and age in the output.
- It only reads frameworks it has a reader or pattern for. The gate says what it could not read
  instead of guessing.
- The output is a draft. A person should review it.
