# Contributing

Design background: [docs/architecture-plan.md](docs/architecture-plan.md). Conventions and module boundaries:
[CLAUDE.md](CLAUDE.md).

## Setup

Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

```bash
pytest --cov=rate_limiter   # tests
ruff check                  # lint
mypy src                    # type-check
```

Run all three before opening a PR (Claude Code users: the `/check` skill does this). When behavior, layout or
commands change, update the markdown docs too (`/sync-docs` does this).

## Optional extras

The base package has no dependencies. When working on an integration, install its extra:

| Area | Extra | Provides |
| --- | --- | --- |
| `server/` | `fastapi` | FastAPI / Starlette |
| `backends/redis.py` | `redis` | `redis-py` (defined in `pyproject.toml`; `dev` also installs `fakeredis`) |
| `client/async_decorator.py` | `httpx` | `httpx` |

Only the `redis` extra is defined in `pyproject.toml` so far; the others are placeholders until the packaging
issue (#40), so for now install those libraries directly (e.g. `pip install fastapi`).

Redis tests run against `fakeredis` by default. To also run the `integration`-marked cases against a real Redis,
set `RATE_LIMITER_REDIS_URL` (e.g. `redis://localhost:6379/15`; the database is flushed).

Keep imports of optional dependencies lazy so `import rate_limiter` works without them.

## Branches and PRs

- Branch per epic, named `RL-<epic number>` (e.g. `RL-1`); one focused change per issue.
- Reference the issue in the PR description (`Closes #N`).
- Keep `core/` and `backends/` free of HTTP concerns, and `server/`/`client/` independent of each other.
