from dataclasses import dataclass, field

import pytest

from rate_limiter.backends import InMemoryBackend
from rate_limiter.client._common import RateLimitExceeded
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.client.decorator import rate_limited
from rate_limiter.core import FixedWindowCounter, TokenBucket
from rate_limiter.core.limiter import RateLimiter


@dataclass
class FakeResponse:
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class FakeClock:
    """A clock that ``sleep`` advances, so waits are instant but still move time forward."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: clock.now)
    return clock


def make_limiter(limit: int = 2, window: int = 10) -> RateLimiter:
    return RateLimiter(FixedWindowCounter(limit=limit, window_seconds=window), InMemoryBackend())


def test_passes_arguments_and_return_value_through(clock: FakeClock) -> None:
    @rate_limited(make_limiter(), key="k", sleep=clock.sleep)
    def add(a: int, b: int = 0) -> int:
        """Adds."""
        return a + b

    assert add(1, b=2) == 3
    assert add.__name__ == "add"
    assert add.__doc__ == "Adds."
    assert clock.sleeps == []


def test_proactive_throttling_waits_for_the_next_window(clock: FakeClock) -> None:
    calls: list[float] = []

    @rate_limited(make_limiter(limit=2, window=10), key="k", sleep=clock.sleep)
    def call() -> None:
        calls.append(clock.now)

    for _ in range(3):
        call()
    assert len(clock.sleeps) == 1
    assert 0 < clock.sleeps[0] <= 10
    assert calls[2] - calls[0] >= clock.sleeps[0]


def test_reactive_retry_uses_retry_after_then_succeeds(clock: FakeClock) -> None:
    responses = [FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200)]

    @rate_limited(make_limiter(limit=100), key="k", retry_policy=RetryPolicy(), sleep=clock.sleep)
    def call() -> FakeResponse:
        return responses.pop(0)

    assert call().status_code == 200
    assert clock.sleeps == [7]
    assert responses == []


def test_reactive_retry_falls_back_to_backoff_without_retry_after(clock: FakeClock) -> None:
    responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200)]
    policy = RetryPolicy(base_delay=1, jitter=False)

    @rate_limited(make_limiter(limit=100), key="k", retry_policy=policy, sleep=clock.sleep)
    def call() -> FakeResponse:
        return responses.pop(0)

    assert call().status_code == 200
    assert clock.sleeps == [1, 2]


def test_gives_back_the_last_429_after_max_retries(clock: FakeClock) -> None:
    attempts = 0

    @rate_limited(
        make_limiter(limit=100),
        key="k",
        retry_policy=RetryPolicy(max_retries=2, jitter=False),
        sleep=clock.sleep,
    )
    def call() -> FakeResponse:
        nonlocal attempts
        attempts += 1
        return FakeResponse(429)

    assert call().status_code == 429
    assert attempts == 3  # first try + 2 retries
    assert len(clock.sleeps) == 2


def test_no_retry_without_a_policy(clock: FakeClock) -> None:
    @rate_limited(make_limiter(limit=100), key="k", sleep=clock.sleep)
    def call() -> FakeResponse:
        return FakeResponse(429)

    assert call().status_code == 429
    assert clock.sleeps == []


def test_non_response_return_values_are_not_retried(clock: FakeClock) -> None:
    @rate_limited(make_limiter(), key="k", retry_policy=RetryPolicy(), sleep=clock.sleep)
    def call() -> str:
        return "not a response"

    assert call() == "not a response"


def test_custom_response_extractor(clock: FakeClock) -> None:
    responses = [{"code": 429, "h": {"Retry-After": "3"}}, {"code": 200, "h": {}}]

    @rate_limited(
        make_limiter(limit=100),
        key="k",
        retry_policy=RetryPolicy(),
        response_extractor=lambda r: (r["code"], r["h"]),
        sleep=clock.sleep,
    )
    def call() -> dict[str, object]:
        return responses.pop(0)

    assert call()["code"] == 200
    assert clock.sleeps == [3]


def test_each_retry_consumes_local_allowance(clock: FakeClock) -> None:
    responses = [FakeResponse(429, {"Retry-After": "0"}), FakeResponse(200)]
    limiter = make_limiter(limit=100)

    @rate_limited(limiter, key="k", retry_policy=RetryPolicy(), sleep=clock.sleep)
    def call() -> FakeResponse:
        return responses.pop(0)

    call()
    assert limiter.check("k").remaining == 100 - 3  # two calls plus this check


def test_cost_that_can_never_fit_raises(clock: FakeClock) -> None:
    limiter = RateLimiter(TokenBucket(rate=1, capacity=2), InMemoryBackend())

    @rate_limited(limiter, key="k", cost=5, sleep=clock.sleep)
    def call() -> None:
        raise AssertionError("must not be called")

    with pytest.raises(RateLimitExceeded):
        call()


def test_context_manager_waits_on_entry(clock: FakeClock) -> None:
    limiter = make_limiter(limit=1, window=10)
    with rate_limited(limiter, key="k", sleep=clock.sleep):
        pass
    assert clock.sleeps == []
    with rate_limited(limiter, key="k", sleep=clock.sleep):
        pass
    assert len(clock.sleeps) == 1


def test_context_manager_does_not_swallow_exceptions(clock: FakeClock) -> None:
    with pytest.raises(ValueError), rate_limited(make_limiter(), key="k", sleep=clock.sleep):
        raise ValueError("boom")
