---
name: check
description: Run the full local lint, type-check and test suite (ruff, mypy, pytest with coverage) and report failures.
---

Run these from the repo root, in order, and keep going even if one fails so all problems are reported at once:

1. `ruff check`
2. `mypy src`
3. `pytest --cov=rate_limiter`

Then summarize: which steps passed, and for each failure the file, line and cause. Do not fix anything unless
asked. If a tool is missing, tell the user to run `pip install -e ".[dev]"`.
