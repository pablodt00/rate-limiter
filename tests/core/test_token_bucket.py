import copy

import pytest

from rate_limiter.core import TokenBucket


def test_new_bucket_starts_full() -> None:
    state, result = TokenBucket(rate=1, capacity=5).check_and_update(None, now=100)
    assert result.allowed
    assert result.remaining == 4
    assert result.limit == 5
    assert state == {"tokens": 4.0, "last_refill": 100}


def test_burst_up_to_capacity_then_denied() -> None:
    bucket = TokenBucket(rate=1, capacity=3)
    state = None
    for _ in range(3):
        state, result = bucket.check_and_update(state, now=0)
        assert result.allowed
    _, result = bucket.check_and_update(state, now=0)
    assert not result.allowed
    assert result.remaining == 0


@pytest.mark.parametrize(
    ("elapsed", "expected_remaining"),
    [(0, 0), (1, 1), (2.5, 4), (100, 9)],
)
def test_refill_over_time_capped_at_capacity(elapsed: float, expected_remaining: int) -> None:
    bucket = TokenBucket(rate=2, capacity=10)
    state = {"tokens": 0.0, "last_refill": 0.0}
    _, result = bucket.check_and_update(state, now=elapsed, cost=1)
    assert result.allowed is (elapsed > 0)
    assert result.remaining == expected_remaining


def test_cost_consumes_multiple_tokens() -> None:
    _, result = TokenBucket(rate=1, capacity=10).check_and_update(None, now=0, cost=4)
    assert result.allowed
    assert result.remaining == 6


def test_denial_reports_retry_and_reset() -> None:
    bucket = TokenBucket(rate=2, capacity=10)
    state = {"tokens": 1.0, "last_refill": 0.0}
    new_state, result = bucket.check_and_update(state, now=0, cost=5)
    assert not result.allowed
    assert result.retry_after == pytest.approx(2.0)  # 4 missing tokens at 2/s
    assert result.reset_after == pytest.approx(4.5)  # 9 missing tokens at 2/s
    assert new_state["tokens"] == 1.0  # nothing consumed on denial


def test_retrying_at_retry_after_succeeds() -> None:
    bucket = TokenBucket(rate=2, capacity=10)
    state = {"tokens": 1.0, "last_refill": 0.0}
    _, denied = bucket.check_and_update(state, now=0, cost=5)
    assert denied.retry_after is not None
    _, retried = bucket.check_and_update(state, now=denied.retry_after, cost=5)
    assert retried.allowed


def test_cost_above_capacity_never_succeeds() -> None:
    _, result = TokenBucket(rate=1, capacity=3).check_and_update(None, now=0, cost=4)
    assert not result.allowed
    assert result.retry_after is None


def test_clock_going_backwards_does_not_drain() -> None:
    bucket = TokenBucket(rate=1, capacity=5)
    state = {"tokens": 3.0, "last_refill": 10.0}
    _, result = bucket.check_and_update(state, now=5, cost=1)
    assert result.allowed
    assert result.remaining == 2


def test_does_not_mutate_input_state() -> None:
    state = {"tokens": 3.0, "last_refill": 0.0}
    snapshot = copy.deepcopy(state)
    new_state, _ = TokenBucket(rate=1, capacity=5).check_and_update(state, now=1)
    assert state == snapshot
    assert new_state is not state


@pytest.mark.parametrize(("rate", "capacity"), [(0, 1), (-1, 1), (1, 0), (1, -2)])
def test_invalid_config_raises(rate: float, capacity: int) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=rate, capacity=capacity)


@pytest.mark.parametrize("cost", [0, -1])
def test_invalid_cost_raises(cost: int) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=1, capacity=1).check_and_update(None, now=0, cost=cost)
