# rate-limiter

A rate-limiting library for Python, for both protecting a server and calling rate-limited APIs politely.

- **Server side:** protect a FastAPI app from too many incoming requests.
- **Client side:** pace and back off calls to third-party APIs so you don't trip their limits.

Both share one core: an algorithm decides, a backend stores state, and a small facade ties them together.

## Status

Work in progress. Here is what exists today:

| Area | Status |
| --- | --- |
| Core algorithms (token bucket, sliding window, fixed window) | Done |
| Storage backends (in-memory, Redis) | Planned |
| `RateLimiter` facade | Planned |
| Client-side helpers (header parsing, backoff, decorators) | Planned |
| FastAPI integration (dependency, middleware) | Planned |

## Install

Requires Python 3.10+. Not published yet, so install from a checkout:

```bash
pip install -e .
```

Optional extras for Redis, FastAPI and async HTTP clients are planned; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Using the algorithms

Algorithms are pure: you hand them the previous state and the current time, and they return the new state and a
result. They never read the clock, so they are easy to test with made-up timestamps.

```python
from rate_limiter.core import TokenBucket

bucket = TokenBucket(rate=1, capacity=3)  # 1 token per second, bursts of up to 3
state = None
for now in (0, 0, 0, 0, 2):
    state, result = bucket.check_and_update(state, now)
    print(now, result.allowed, result.remaining, result.retry_after)
```

`SlidingWindowCounter(limit, window_seconds)` and `FixedWindowCounter(limit, window_seconds)` work the same way.
A request whose cost can never fit is denied with `retry_after=None`.

## Learn more

- [Architecture plan](docs/architecture-plan.md): the design and planned modules.
- [Contributing](CONTRIBUTING.md): setup, checks and conventions.

## License

MIT, see [LICENSE](LICENSE).
