---
name: plan-issue
description: Plan the implementation of a GitHub issue from just its link. If the issue is an epic, plan all its sub-issues too. Plan only; does not implement.
---

Argument: a GitHub issue URL (or `#N` for this repo). If none is given, ask for it.

1. Make sure plan mode is on (enter it if not).
2. Read the issue with the GitHub tools (load them via ToolSearch if needed). It is an **epic** if it has the
   `epic` label or any sub-issues. For an epic, read every sub-issue and its comments and work out the order from
   their "Depends on" notes. For a single issue, read it and its parent (if any) for context.
3. Read `CLAUDE.md` and `docs/architecture-plan.md`, then look at the existing code and tests so the plan reuses
   what is already there.
4. Ask the user only about real design choices they must make. Use sensible defaults for everything else.
5. Write the plan in everyday language:
   - A short paragraph on why the work is needed.
   - A numbered list. Each item is one or two plain sentences saying what will be done and why. No code blocks and
     no field-by-field detail; mention files only in passing.
   - A closing line on how to check the result (run `/check`).
6. Ask for approval, then stop. Do not start implementing unless the user says so.

Rules: make no git operations (no branch, commit, push or PR) and post nothing to GitHub unless asked.
