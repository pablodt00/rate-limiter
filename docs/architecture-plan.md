# Architecture plan

> Reconstructed from the GitHub issue tracker (epics #1–#9 and their sub-issues #10–#40). If it drifts from
> what was originally agreed, the issues and this file should be reconciled.

One library, two use cases:

- **Server-side** — protect a FastAPI app from too many incoming requests.
- **Client-side** — help code that *calls* third-party rate-limited APIs avoid tripping their limits.

Both share the same core: an `Algorithm` decides, a `RateLimiterBackend` stores state atomically, and a
`RateLimiter` facade wires the two together.

## Package layout

```
src/rate_limiter/
├── __init__.py
├── py.typed
├── core/
│   ├── result.py        # RateLimitResult
│   ├── algorithms.py    # TokenBucket, SlidingWindowCounter, FixedWindowCounter (pure)
│   └── limiter.py       # RateLimiter facade
├── backends/
│   ├── base.py          # RateLimiterBackend (ABC)
│   ├── memory.py        # InMemoryBackend (stdlib only, default)
│   └── redis.py         # RedisBackend (optional extra, Lua scripts)
├── server/              # optional extra: fastapi
│   ├── keys.py          # by_ip, by_header, by_route, combine
│   ├── fastapi_dependency.py   # rate_limit() dependency
│   └── fastapi_middleware.py   # RateLimitMiddleware (raw ASGI)
└── client/
    ├── headers.py       # Retry-After / X-RateLimit-* parsing
    ├── backoff.py       # RetryPolicy, is_rate_limited_response
    ├── decorator.py     # rate_limited (sync)
    └── async_decorator.py      # async_rate_limited (needs an async HTTP lib)
```

## Module boundaries

- `core/` and `backends/` know nothing about HTTP, FastAPI, `requests` or `httpx`.
- `server/` and `client/` each depend only on `core` + `backends`, never on each other.
- Optional-dependency modules (`backends/redis.py`, `server/*`, `client/async_decorator.py`) import their
  extra lazily; a bare `import rate_limiter` must never require `fastapi`, `redis` or `httpx`.

## Core (Epic 1)

`RateLimitResult` (frozen dataclass): `allowed`, `remaining`, `limit`, `reset_after`, `retry_after | None`.
The single value object returned by every algorithm and backend; the server turns it into headers, the client
into a sleep duration.

Algorithms are **pure**:

```python
def check_and_update(self, state: dict | None, now: float, cost: int = 1) -> tuple[dict, RateLimitResult]
```

- No I/O, no clock reads (`now` is passed in), no mutation of the input `state`. Fully unit-testable with
  fabricated timestamps.
- `Algorithm` is a `Protocol` (in `core/algorithms.py`) with exactly that method; algorithms are frozen
  dataclasses that validate their config (`ValueError` unless positive) and `cost >= 1`.
- `TokenBucket(rate, capacity)` — state `{tokens, last_refill}`; starts full, bursts up to `capacity`.
- `SlidingWindowCounter(limit, window_seconds)` — approximated sliding window, O(1) state
  `{window, current, previous}` (no timestamp log); `retry_after` is computed exactly.
- `FixedWindowCounter(limit, window_seconds)` — simplest; state `{window, count}` with epoch-aligned windows
  (a one-day window resets at midnight UTC); good for quotas like "1000/day" and as a correctness baseline for
  backend tests.
- A denied request consumes nothing. A `cost` that can never fit (above `capacity`/`limit`) is denied with
  `retry_after=None`, meaning "never".

## Backends (Epic 2)

```python
class RateLimiterBackend(ABC):
    def increment(self, key, algorithm, now, cost=1) -> RateLimitResult
    async def aincrement(self, key, algorithm, now, cost=1) -> RateLimitResult  # default delegates to increment
    def reset(self, key) -> None
    def peek(self, key, algorithm, now) -> RateLimitResult                      # read-only
```

The backend receives the `Algorithm` object itself, so each algorithm's state shape stays opaque to it. The
backend — not the algorithm — owns atomic load → update → persist per key; race-condition safety lives here.

- **`InMemoryBackend`**: stdlib only; one `threading.Lock` around a `dict[str, dict]`. The single global lock
  serializes all keys — an intentional v1 simplification, fine for single-process use. Covered by a
  multi-threaded regression test asserting admitted count never exceeds the allowance.
- **`RedisBackend`** (`rate-limiter[redis]`): Lua scripts via `register_script`/`EVALSHA` for atomicity
  (`MULTI`/`EXEC` cannot express read-then-conditionally-write without a slow `WATCH` retry loop). State in a
  hash with a TTL of a couple of window lengths so abandoned keys expire. Scripts for all three algorithms.
  True async path via `redis.asyncio` (in `redis-py>=4.2`; not the deprecated `aioredis`). Tested with
  `fakeredis`; an env-gated `@pytest.mark.integration` suite runs against a real Redis.

## Facade (Epic 3)

```python
class RateLimiter:
    def __init__(self, algorithm, backend, key_prefix="ratelimit")
    def check(self, key, cost=1) -> RateLimitResult
    async def acheck(self, key, cost=1) -> RateLimitResult
```

`time.time()` is read only here, at the outermost call site. Server and client both construct and hold this
same object.

## Client side (Epic 4)

- `headers.py`: `parse_retry_after` (delta-seconds and HTTP-date, RFC 9110) and `parse_rate_limit_headers`
  over a plain `Mapping[str, str]` (library-agnostic). Vendor header names (e.g. OpenAI's
  `x-ratelimit-remaining-requests`) go through an extensible alias registry.
- `backoff.py`: `RetryPolicy(max_retries, base_delay, max_delay, jitter, respect_retry_after)` — exponential
  backoff with full jitter, capped, overridden by `Retry-After` when present.
- `decorator.py` / `async_decorator.py`: `rate_limited` / `async_rate_limited`, usable as decorator or context
  manager. Two behaviors: **proactive** local throttling via `limiter.check` before the call, and **reactive**
  retry on a 429 using parsed headers and `RetryPolicy`. A `response_extractor` (default: `.headers`) adapts to
  the HTTP library.

## Server side (Epic 5)

- `keys.py`: `KeyFunc = Callable[[Request], str | Awaitable[str]]` with `by_ip`, `by_header`, `by_route`,
  `combine`. Any user function of that shape is a custom key function.
- `rate_limit(limiter, key_func=by_ip, cost=1)`: FastAPI dependency; sets `X-RateLimit-Limit/Remaining/Reset`,
  raises 429 with retry headers when denied.
- `RateLimitMiddleware(app, limiter, key_func, cost, exempt_paths)`: **raw ASGI**, deliberately not
  `BaseHTTPMiddleware` (streaming/background-task quirks). Injects headers on `http.response.start`; returns a
  429 JSON response when denied. Header-building code is shared with the dependency so both produce the same
  header contract.

## Docs, testing, CI (Epics 6–8)

- Examples: `examples/fastapi_app.py`, `client_sync_requests.py`, `client_async_httpx.py`; top-level README.
- E2E: real ASGI server on loopback + real HTTP client, for in-memory and Redis backends, plus a client
  pacing/backoff scenario against a real server round-trip.
- CI: GitHub Actions matrix, `ruff check`, `mypy src`, `pytest --cov=rate_limiter`; `fakeredis` by default, an
  optional non-blocking job with a real Redis service for integration tests.
- Packaging: extras `fastapi`, `redis`, `httpx`, `requests`, `dev`, `all`; resolve the PyPI distribution name
  (`rate-limiter` may be taken) before first publish.

## Epic / issue breakdown

| Epic | Scope | Issues |
| --- | --- | --- |
| 0 (#1) | Project & Claude tooling setup | #10–#14 |
| 1 (#2) | Core algorithms | #15–#18 |
| 2 (#3) | Storage backends | #19–#23 |
| 3 (#4) | Core limiter facade | #24 |
| 4 (#5) | Client-side rate limiting | #25–#28 |
| 5 (#6) | Server-side / FastAPI integration | #29–#31 |
| 6 (#7) | Examples & documentation | #32–#35 |
| 7 (#8) | End-to-end testing | #36–#38 |
| 8 (#9) | CI/CD & packaging | #39, #40 |

Dependencies: Epic 1 → Epic 2 → Epic 3 → Epics 4 and 5 (parallel) → Epic 6 → Epic 7. Epic 8 (CI/packaging)
runs alongside.
