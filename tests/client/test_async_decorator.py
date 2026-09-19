from dataclasses import dataclass, field

import pytest

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client._common import RateLimitExceeded
from rate_limiter.client.async_decorator import async_rate_limited
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.core import FixedWindowCounter, TokenBucket
from rate_limiter.core.limiter import RateLimiter


@dataclass
class FakeAsyncResponse:
    """Shaped like ``aiohttp.ClientResponse``: ``status`` rather than ``status_code``."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: clock.now)
    return clock


def make_limiter(limit: int = 2, window: int = 10) -> RateLimiter:
    return RateLimiter(FixedWindowCounter(limit=limit, window_seconds=window), InMemoryBackend())


@pytest.mark.asyncio
async def test_passes_arguments_and_return_value_through(clock: FakeClock) -> None:
    @async_rate_limited(make_limiter(), key="k", sleep=clock.sleep)
    async def add(a: int, b: int = 0) -> int:
        """Adds."""
        return a + b

    assert await add(1, b=2) == 3
    assert add.__name__ == "add"
    assert add.__doc__ == "Adds."
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_proactive_throttling_waits_for_the_next_window(clock: FakeClock) -> None:
    @async_rate_limited(make_limiter(limit=2, window=10), key="k", sleep=clock.sleep)
    async def call() -> None:
        return None

    for _ in range(3):
        await call()
    assert len(clock.sleeps) == 1
    assert 0 < clock.sleeps[0] <= 10


@pytest.mark.asyncio
async def test_reactive_retry_uses_retry_after_then_succeeds(clock: FakeClock) -> None:
    responses = [FakeAsyncResponse(429, {"Retry-After": "7"}), FakeAsyncResponse(200)]

    @async_rate_limited(
        make_limiter(limit=100), key="k", retry_policy=RetryPolicy(), sleep=clock.sleep
    )
    async def call() -> FakeAsyncResponse:
        return responses.pop(0)

    assert (await call()).status == 200
    assert clock.sleeps == [7]


@pytest.mark.asyncio
async def test_reactive_retry_falls_back_to_backoff(clock: FakeClock) -> None:
    responses = [FakeAsyncResponse(429), FakeAsyncResponse(429), FakeAsyncResponse(200)]
    policy = RetryPolicy(base_delay=1, jitter=False)

    @async_rate_limited(make_limiter(limit=100), key="k", retry_policy=policy, sleep=clock.sleep)
    async def call() -> FakeAsyncResponse:
        return responses.pop(0)

    assert (await call()).status == 200
    assert clock.sleeps == [1, 2]


@pytest.mark.asyncio
async def test_gives_back_the_last_429_after_max_retries(clock: FakeClock) -> None:
    attempts = 0

    @async_rate_limited(
        make_limiter(limit=100),
        key="k",
        retry_policy=RetryPolicy(max_retries=1, jitter=False),
        sleep=clock.sleep,
    )
    async def call() -> FakeAsyncResponse:
        nonlocal attempts
        attempts += 1
        return FakeAsyncResponse(429)

    assert (await call()).status == 429
    assert attempts == 2


@pytest.mark.asyncio
async def test_no_retry_without_a_policy(clock: FakeClock) -> None:
    @async_rate_limited(make_limiter(limit=100), key="k", sleep=clock.sleep)
    async def call() -> FakeAsyncResponse:
        return FakeAsyncResponse(429)

    assert (await call()).status == 429
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_cost_that_can_never_fit_raises(clock: FakeClock) -> None:
    limiter = RateLimiter(TokenBucket(rate=1, capacity=2), InMemoryBackend())

    @async_rate_limited(limiter, key="k", cost=5, sleep=clock.sleep)
    async def call() -> None:
        raise AssertionError("must not be called")

    with pytest.raises(RateLimitExceeded):
        await call()


@pytest.mark.asyncio
async def test_async_context_manager_waits_on_entry(clock: FakeClock) -> None:
    limiter = make_limiter(limit=1, window=10)
    async with async_rate_limited(limiter, key="k", sleep=clock.sleep):
        pass
    assert clock.sleeps == []
    async with async_rate_limited(limiter, key="k", sleep=clock.sleep):
        pass
    assert len(clock.sleeps) == 1


@pytest.mark.asyncio
async def test_async_context_manager_does_not_swallow_exceptions(clock: FakeClock) -> None:
    with pytest.raises(ValueError):
        async with async_rate_limited(make_limiter(), key="k", sleep=clock.sleep):
            raise ValueError("boom")
