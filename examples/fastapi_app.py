"""A FastAPI app protected two ways: a global per-IP limit and a stricter per-API-key limit on one route.

Run it from the repo root:

    uvicorn examples.fastapi_app:app

Then hammer it:

    for i in $(seq 1 12); do curl -si localhost:8000/ | head -n 1; done
    for i in $(seq 1 5); do curl -si -H 'X-API-Key: demo' localhost:8000/limited | head -n 1; done
"""

from fastapi import Depends, FastAPI

from rate_limiter.backends import InMemoryBackend
from rate_limiter.core import FixedWindowCounter, TokenBucket
from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server.fastapi_dependency import rate_limit
from rate_limiter.server.fastapi_middleware import RateLimitMiddleware
from rate_limiter.server.keys import by_header, by_ip

backend = InMemoryBackend()

# Every client IP may burst up to 10 requests, refilling at 5 per second.
per_ip = RateLimiter(TokenBucket(rate=5, capacity=10), backend, key_prefix="ip")

# On top of that, each API key gets only 3 requests per 10 seconds on the expensive route.
per_api_key = RateLimiter(FixedWindowCounter(limit=3, window_seconds=10), backend, key_prefix="key")

app = FastAPI(title="rate-limiter example")
app.add_middleware(RateLimitMiddleware, limiter=per_ip, key_func=by_ip, exempt_paths=["/health"])


@app.get("/")
def index() -> dict[str, str]:
    return {"message": "hello"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}  # exempt from the global limit


@app.get(
    "/limited", dependencies=[Depends(rate_limit(per_api_key, key_func=by_header("X-API-Key")))]
)
def limited() -> dict[str, str]:
    return {"message": "you are within your API key's allowance"}
