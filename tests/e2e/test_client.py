"""``rate_limited`` / ``async_rate_limited`` driving the example server over a real network round-trip.

The decorators' ``sleep`` advances the fake clock instead of waiting, so pacing and ``Retry-After`` waits are
exact, fast, and seen identically by the client's limiter and by the server.
"""

import httpx
import pytest
import requests

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client.async_decorator import async_rate_limited
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.client.decorator import rate_limited
from rate_limiter.core import TokenBucket
from rate_limiter.core.limiter import RateLimiter
from tests.conftest import Clock
from tests.e2e.conftest import LiveServer

API_KEY = {"X-API-Key": "demo"}
CALLS = 40  # far more than the server's burst of 10


def _client_limiter(rate: float, capacity: int) -> RateLimiter:
    return RateLimiter(TokenBucket(rate=rate, capacity=capacity), InMemoryBackend())


def test_sync_pacing_keeps_the_server_from_ever_answering_429(
    live_server: LiveServer, clock: Clock
) -> None:
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    # Slightly below the server's 5/s (burst 10) so float rounding cannot tip us over.
    @rate_limited(_client_limiter(rate=4, capacity=10), key="api", sleep=sleep)
    def fetch() -> requests.Response:
        return requests.get(f"{live_server.url}/", timeout=10)

    statuses = [fetch().status_code for _ in range(CALLS)]

    assert statuses == [200] * CALLS
    assert len(live_server.hits) == CALLS
    assert sum(sleeps) == (CALLS - 10) / 4  # the first 10 are the burst, then one call every 0.25s


@pytest.mark.asyncio
async def test_async_pacing_keeps_the_server_from_ever_answering_429(
    live_server: LiveServer, clock: Clock
) -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    async with httpx.AsyncClient(timeout=10) as client:

        @async_rate_limited(_client_limiter(rate=4, capacity=10), key="api", sleep=sleep)
        async def fetch() -> httpx.Response:
            return await client.get(f"{live_server.url}/")

        statuses = [(await fetch()).status_code for _ in range(CALLS)]

    assert statuses == [200] * CALLS
    assert len(live_server.hits) == CALLS
    assert sum(sleeps) == (CALLS - 10) / 4


def test_sync_backs_off_on_real_429_using_retry_after(
    live_server: LiveServer, clock: Clock
) -> None:
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    # A generous local limiter, so every 429 here comes from the server (3 per 10s per API key).
    @rate_limited(
        _client_limiter(rate=100, capacity=100),
        key="api",
        retry_policy=RetryPolicy(max_retries=3),
        sleep=sleep,
    )
    def fetch() -> requests.Response:
        return requests.get(f"{live_server.url}/limited", headers=API_KEY, timeout=10)

    statuses = [fetch().status_code for _ in range(5)]

    assert statuses == [200] * 5  # the 4th call got a 429, waited out the window, then succeeded
    assert sleeps == [10]  # exactly the server's Retry-After
    assert len(live_server.hits) == 6  # 5 calls + 1 retry


@pytest.mark.asyncio
async def test_async_backs_off_on_real_429_using_retry_after(
    live_server: LiveServer, clock: Clock
) -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    async with httpx.AsyncClient(timeout=10) as client:

        @async_rate_limited(
            _client_limiter(rate=100, capacity=100),
            key="api",
            retry_policy=RetryPolicy(max_retries=3),
            sleep=sleep,
        )
        async def fetch() -> httpx.Response:
            return await client.get(f"{live_server.url}/limited", headers=API_KEY)

        statuses = [(await fetch()).status_code for _ in range(5)]

    assert statuses == [200] * 5
    assert sleeps == [10]
    assert len(live_server.hits) == 6


def test_gives_up_and_returns_the_429_when_retries_run_out(
    live_server: LiveServer, clock: Clock
) -> None:
    sleeps: list[float] = []

    # This sleep does not advance the clock, so the server keeps saying 429.
    @rate_limited(
        _client_limiter(rate=100, capacity=100),
        key="api",
        retry_policy=RetryPolicy(max_retries=2),
        sleep=sleeps.append,
    )
    def fetch() -> requests.Response:
        return requests.get(f"{live_server.url}/limited", headers=API_KEY, timeout=10)

    for _ in range(3):
        assert fetch().status_code == 200
    final = fetch()

    assert final.status_code == 429
    assert len(sleeps) == 2  # two retries, then the 429 is handed back to the caller
    assert len(live_server.hits) == 3 + 1 + 2
