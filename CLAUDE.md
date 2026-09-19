# CLAUDE.md

Python rate-limiting library with two use cases: protecting a FastAPI server, and pacing/backing off calls to
third-party APIs. Full design: [docs/architecture-plan.md](docs/architecture-plan.md).

## Layout

`src/rate_limiter/` with `core/` (algorithms, result, limiter facade), `backends/` (base, memory, redis),
`server/` (FastAPI integration) and `client/` (headers, backoff, decorators).

## Module boundaries

- `core/` and `backends/` know nothing about HTTP, FastAPI, `requests` or `httpx`.
- `server/` and `client/` each depend only on `core` + `backends`, never on each other.

## Conventions

- Algorithms in `core/algorithms.py` are pure functions taking `now: float`. Never call `time.time()` inside
  an algorithm or backend; only `RateLimiter.check`/`acheck` default `now` to the current time.
- Algorithms must not mutate the `state` they receive; return a new state.
- Optional-dependency modules (`backends/redis.py`, `server/*`, `client/async_decorator.py`) must import their
  extra lazily, so a bare `import rate_limiter` never requires `fastapi`, `redis` or `httpx`.
- The backend owns atomic load-update-persist per key; race-safety lives there, not in algorithms.

## Commands

```bash
pip install -e ".[dev]"      # dev setup
ruff check                   # lint
mypy src                     # type-check
pytest --cov=rate_limiter    # tests
```

The `/check` skill runs all three. See [CONTRIBUTING.md](CONTRIBUTING.md) for more.
