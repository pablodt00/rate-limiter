import pytest

from rate_limiter.client.backoff import RetryPolicy, is_rate_limited_response
from rate_limiter.client.headers import ParsedRateLimitInfo


def test_exponential_growth_without_jitter() -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=100, jitter=False)
    assert [policy.compute_delay(a) for a in range(4)] == [0.5, 1, 2, 4]


def test_delay_is_capped() -> None:
    policy = RetryPolicy(base_delay=1, max_delay=5, jitter=False)
    assert policy.compute_delay(10) == 5
    assert policy.compute_delay(10_000) == 5


def test_full_jitter_scales_the_ceiling() -> None:
    policy = RetryPolicy(base_delay=2, max_delay=100, random_func=lambda: 0.25)
    assert policy.compute_delay(2) == pytest.approx(2)  # ceiling 8 * 0.25


def test_jitter_stays_within_bounds() -> None:
    policy = RetryPolicy(base_delay=1, max_delay=10)
    for attempt in range(8):
        assert 0 <= policy.compute_delay(attempt) <= min(10, 2**attempt)


def test_retry_after_overrides_backoff() -> None:
    policy = RetryPolicy(jitter=False)
    assert policy.compute_delay(0, ParsedRateLimitInfo(retry_after=12)) == 12


def test_retry_after_can_exceed_max_delay() -> None:
    policy = RetryPolicy(max_delay=5, jitter=False)
    assert policy.compute_delay(0, ParsedRateLimitInfo(retry_after=60)) == 60


def test_retry_after_ignored_when_disabled() -> None:
    policy = RetryPolicy(base_delay=1, jitter=False, respect_retry_after=False)
    assert policy.compute_delay(0, ParsedRateLimitInfo(retry_after=60)) == 1


def test_falls_back_to_backoff_without_retry_after() -> None:
    policy = RetryPolicy(base_delay=1, jitter=False)
    assert policy.compute_delay(1, ParsedRateLimitInfo(remaining=0)) == 2
    assert policy.compute_delay(1, None) == 2


def test_is_rate_limited_response() -> None:
    assert is_rate_limited_response(429)
    assert not is_rate_limited_response(200)
    assert not is_rate_limited_response(503)
