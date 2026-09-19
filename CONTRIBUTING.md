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

`tests/e2e/` starts the example app (`examples/fastapi_app.py`) on a real `uvicorn` server on loopback and drives
it with real `httpx`/`requests` clients, against the in-memory backend and Redis (see below). It uses a fake clock, so
it needs no sleeping. `uvicorn` comes with the `dev` extra.

Run all three before opening a PR (Claude Code users: the `/check` skill does this). When behavior, layout or
commands change, update the markdown docs too (`/sync-docs` does this).

## Optional extras

The base package has no dependencies. When working on an integration, install its extra:

| Area | Extra | Provides |
| --- | --- | --- |
| `server/` | `fastapi` | FastAPI / Starlette |
| `backends/redis.py` | `redis` | `redis-py` (`dev` also installs `fakeredis`) |
| `tests/e2e/` | (none) | `dev` installs `uvicorn` to serve the example app |
| `examples/client_async_httpx.py` | `httpx` | `httpx` |
| `examples/client_sync_requests.py` | `requests` | `requests` |

`dev` installs all of these, so `pip install -e ".[dev]"` is enough to run every test and example. The `all` extra
installs every optional integration (fastapi, redis, httpx, requests) without the dev tooling.

Redis tests (including the E2E ones) run against `fakeredis` by default. To also run the `integration`-marked cases
against a real Redis, set `RATE_LIMITER_REDIS_URL` (e.g. `redis://localhost:6379/15`; the database is flushed).

Keep imports of optional dependencies lazy so `import rate_limiter` works without them.

## CI

`.github/workflows/ci.yml` runs `ruff check`, `mypy src` and `pytest --cov=rate_limiter` on Python 3.10–3.13 for
every push to `master` and every PR. A separate, non-blocking job runs the `integration` tests against a Redis
service container.

## Publishing

The PyPI distribution name is `fastapi-ratelimit-kit` (`rate-limiter` is already taken; the new name was checked
as free on 2026-09-20). The import package stays `rate_limiter`.

## Branches and PRs

- Branch per epic, named `RL-<epic number>` (e.g. `RL-1`); one focused change per issue.
- Reference the issue in the PR description (`Closes #N`).
- Keep `core/` and `backends/` free of HTTP concerns, and `server/`/`client/` independent of each other.
