"""Call a rate-limited API politely with ``requests``: pace ourselves locally and back off on 429.

Start the example server in another terminal, then run this:

    uvicorn examples.fastapi_app:app
    python examples/client_sync_requests.py [URL]

The server only allows 3 requests per 10 seconds per API key, so some calls get a 429; watch the client wait
for the ``Retry-After`` the server sends and then succeed.
"""

import sys
import time

import requests

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.client.decorator import rate_limited
from rate_limiter.core import TokenBucket
from rate_limiter.core.limiter import RateLimiter

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/limited"

# Our own politeness: at most 2 calls per second, bursts of 2.
limiter = RateLimiter(TokenBucket(rate=2, capacity=2), InMemoryBackend())
started = time.monotonic()


def logging_sleep(seconds: float) -> None:
    print(f"  [{time.monotonic() - started:5.1f}s] waiting {seconds:.1f}s")
    time.sleep(seconds)


@rate_limited(limiter, key="demo", retry_policy=RetryPolicy(max_retries=3), sleep=logging_sleep)
def fetch() -> requests.Response:
    return requests.get(URL, headers={"X-API-Key": "demo"}, timeout=10)


if __name__ == "__main__":
    for i in range(1, 7):
        response = fetch()
        print(f"[{time.monotonic() - started:5.1f}s] call {i}: HTTP {response.status_code}")
