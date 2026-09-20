# rate-limiter

[![CI](https://github.com/pablodt00/rate-limiter/actions/workflows/ci.yml/badge.svg)](https://github.com/pablodt00/rate-limiter/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A rate-limiting library for Python, for both protecting a server and calling rate-limited APIs politely.

- **Server side:** protect a FastAPI app from too many incoming requests.
- **Client side:** pace and back off calls to third-party APIs so you don't trip their limits.

Both share one core: an algorithm decides, a backend stores state, and a small facade (`RateLimiter`) ties them
together.

## Install

Requires Python 3.10+. Not published yet, so install from a checkout:

```bash
pip install -e .                 # core + in-memory backend, no third-party dependencies
pip install -e ".[redis]"        # Redis backend
pip install -e ".[fastapi]"      # FastAPI dependency and middleware
pip install -e ".[httpx]"        # only needed to run the async client example
pip install -e ".[requests]"     # only needed to run the sync client example
```

The decorators work with any HTTP library, so the `httpx` and `requests` extras are just for the examples.
A plain `import rate_limiter` never needs any extra.

## Quick start: protect a FastAPI app

A global per-IP limit with a middleware, plus a stricter per-API-key limit on one route. Full version in
[`examples/fastapi_app.py`](examples/fastapi_app.py); run it with `uvicorn examples.fastapi_app:app`.

```python
from fastapi import Depends, FastAPI

from rate_limiter.backends import InMemoryBackend
from rate_limiter.core import FixedWindowCounter, TokenBucket
from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server.fastapi_dependency import rate_limit
from rate_limiter.server.fastapi_middleware import RateLimitMiddleware
from rate_limiter.server.keys import by_header, by_ip

backend = InMemoryBackend()
per_ip = RateLimiter(TokenBucket(rate=5, capacity=10), backend, key_prefix="ip")
per_api_key = RateLimiter(FixedWindowCounter(limit=3, window_seconds=10), backend, key_prefix="key")

app = FastAPI()
app.add_middleware(RateLimitMiddleware, limiter=per_ip, key_func=by_ip, exempt_paths=["/health"])


@app.get(
    "/limited", dependencies=[Depends(rate_limit(per_api_key, key_func=by_header("X-API-Key")))]
)
def limited() -> dict[str, str]:
    return {"message": "ok"}
```

Every response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`. Callers over their
allowance get a `429` with `Retry-After`. Key functions decide who is who: `by_ip`, `by_header(name)`,
`by_route` and `combine(...)` are included, and any function that takes a request and returns a string works.

## Quick start: call a rate-limited API

`rate_limited` waits locally until your own limiter allows the call, and if the API still answers `429` it backs
off (using `Retry-After` when sent) and tries again. Runnable versions:
[`examples/client_sync_requests.py`](examples/client_sync_requests.py) and
[`examples/client_async_httpx.py`](examples/client_async_httpx.py).

```python
import requests

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.client.decorator import rate_limited
from rate_limiter.core import TokenBucket
from rate_limiter.core.limiter import RateLimiter

limiter = RateLimiter(TokenBucket(rate=2, capacity=2), InMemoryBackend())


@rate_limited(limiter, key="some-api", retry_policy=RetryPolicy(max_retries=3))
def fetch() -> requests.Response:
    return requests.get("https://api.example.com/items")
```

For `async def` code use `async_rate_limited` from `rate_limiter.client.async_decorator`; it works the same way.
Both can also be used as a context manager (`with rate_limited(...):`), which only does the local waiting. If a
response is not a `requests`, `httpx` or `aiohttp` one, pass `response_extractor` to say where the status code
and headers are. The header parsing (`parse_retry_after`, `parse_rate_limit_headers`) is also usable on its own
and can be taught new vendor header names with `register_header_aliases`.

## Choosing a backend

| Backend | Use it when |
| --- | --- |
| `InMemoryBackend` | One process (a single worker, a script, tests). Nothing to install, but limits are not shared between processes. |
| `RedisBackend` | Several workers or servers must share one limit. Needs `redis`; you pass in clients you already built. |

```python
import redis
from rate_limiter.backends.redis import RedisBackend

backend = RedisBackend(redis.Redis())  # add async_client=redis.asyncio.Redis() to use acheck
```

## Choosing an algorithm

| Algorithm | Good for |
| --- | --- |
| `TokenBucket(rate, capacity)` | Allowing short bursts while holding a steady average, e.g. pacing API calls. |
| `SlidingWindowCounter(limit, window_seconds)` | Smooth "N per window" limits without the boundary spike of a fixed window. Approximate, tiny state. |
| `FixedWindowCounter(limit, window_seconds)` | Simple quotas like "1000 per day". Windows are aligned to the clock, so a caller can use two windows' worth around a boundary. |

Algorithms are pure functions: hand them the previous state and the current time and they return the new state
and a result, so they are easy to test with made-up timestamps. Denied requests consume nothing, and a request
whose cost can never fit is denied with `retry_after=None`.

## Using the facade directly

The common building blocks are importable straight from `rate_limiter`.

```python
from rate_limiter import FixedWindowCounter, InMemoryBackend, RateLimiter

limiter = RateLimiter(FixedWindowCounter(limit=2, window_seconds=60), InMemoryBackend())
for _ in range(3):
    print(limiter.check("user:42").allowed)  # True, True, False
```

`check` and `acheck` read the clock so nothing else has to. Backends also offer `peek` (look without consuming)
and `reset`.

## Learn more

- [Examples](examples/): three runnable scripts for the quick starts above.
- [Architecture plan](docs/architecture-plan.md): the design and modules.
- [Changelog](CHANGELOG.md): what changed in each release.
- [Contributing](CONTRIBUTING.md): setup, checks and conventions.

## License

MIT, see [LICENSE](LICENSE).
