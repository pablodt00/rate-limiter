---
name: sync-docs
description: Bring every markdown doc in the repo (README, CONTRIBUTING, CLAUDE.md, docs/, skill files) back in line with the code. Use after changing behavior, layout, commands or dependencies.
---

1. List the tracked markdown files (`git ls-files '*.md'`).
2. Compare each one with reality and note anything stale:
   - package layout and module names against `src/`
   - commands, extras and tool settings against `pyproject.toml` and any CI config
   - the README status table against what is actually implemented
   - epic and issue references against the tracker, when GitHub access is available
   - links between docs and to files, which must still resolve
3. Fix stale statements in place with the smallest edit that makes them true. Keep each file's tone, and do not
   invent features, reword for style, or document things that do not exist yet as if they did.
4. Report briefly what changed and anything you could not decide.

Rules: make no git operations. If a fact cannot be verified from the repo, leave it and mention it.
