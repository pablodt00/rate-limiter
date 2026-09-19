"""The async twin of ``client_sync_requests.py``, using ``httpx.AsyncClient``.

    uvicorn examples.fastapi_app:app
    python examples/client_async_httpx.py [URL]

The calls run concurrently, but the shared limiter still paces them and each one backs off on its own 429.
"""

import asyncio
import sys
import time

import httpx

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client.async_decorator import async_rate_limited
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.core import TokenBucket
from rate_limiter.core.limiter import RateLimiter

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/limited"

limiter = RateLimiter(TokenBucket(rate=2, capacity=2), InMemoryBackend())
started = time.monotonic()


async def logging_sleep(seconds: float) -> None:
    print(f"  [{time.monotonic() - started:5.1f}s] waiting {seconds:.1f}s")
    await asyncio.sleep(seconds)


async def main() -> None:
    async with httpx.AsyncClient(headers={"X-API-Key": "demo"}, timeout=10) as client:

        @async_rate_limited(
            limiter, key="demo", retry_policy=RetryPolicy(max_retries=3), sleep=logging_sleep
        )
        async def fetch() -> httpx.Response:
            return await client.get(URL)

        async def call(i: int) -> None:
            response = await fetch()
            print(f"[{time.monotonic() - started:5.1f}s] call {i}: HTTP {response.status_code}")

        await asyncio.gather(*(call(i) for i in range(1, 7)))


if __name__ == "__main__":
    asyncio.run(main())
