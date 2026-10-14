# Draft: `team-task` step 1 with acceptance-criteria candidates

Replace step 1 of `~/.claude/commands/team-task.md` with the text below. Nothing here runs by itself; the orchestrator runs the one command in it. The rest of `team-task` is unchanged.

---

1. **Acceptance criteria.** Restate the task as a numbered list of acceptance criteria. If any are missing or ambiguous, ask me and wait for confirmation.
   - **Candidates from the code** (when the repo is a git repo with a CodeGraph index). Before restating, run:
     `python3 -I /home/arep/research/prd-assistant/bin/prd_criteria.py lookup "<repo path>" "<the task text>"`
     - Exit 0: read the output. Its first lines say which commit the facts come from, how old they are and whether the working tree has changed files; carry that into the criteria.
     - Exit 2 or 3: continue without candidates and tell me why (the reason is on stderr).
     - "No match": use the route groups it lists to find the right area, and `show --id <id>` for one candidate in full; do not invent candidates.
   - Treat candidates as **evidence, not as criteria**. For every criterion that rests on a candidate, cite its id (for example `C-ROLE-014`) and label it **preserve** (the behaviour must stay as it is) or **change** (the task alters it; say how).
   - Candidates marked `(derived)` are inferences (a role is refused because the endpoint lists other roles). Label them derived in the criterion and do not state an HTTP status for them.
   - If a criterion rests on a candidate whose trust note says something was not read (for example "router-level dependencies are not followed" or "0 of 15 screens were joined to endpoints"), tell me before step 2 and ask whether to check it by hand.
   - Never write a role, field, limit or message into a criterion unless it is in a candidate or in my task text.
