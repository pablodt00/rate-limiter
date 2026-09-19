import copy

import pytest

from rate_limiter.core import FixedWindowCounter


def test_allows_until_limit_then_denies() -> None:
    counter = FixedWindowCounter(limit=3, window_seconds=10)
    state = None
    for expected_remaining in (2, 1, 0):
        state, result = counter.check_and_update(state, now=1)
        assert result.allowed
        assert result.remaining == expected_remaining
    _, result = counter.check_and_update(state, now=1)
    assert not result.allowed
    assert result.remaining == 0
    assert result.retry_after == pytest.approx(9)
    assert result.reset_after == pytest.approx(9)


@pytest.mark.parametrize(
    ("now", "allowed"),
    [(9.999, False), (10, True), (10.5, True)],
)
def test_window_resets_at_boundary(now: float, allowed: bool) -> None:
    counter = FixedWindowCounter(limit=1, window_seconds=10)
    state, _ = counter.check_and_update(None, now=0)
    _, result = counter.check_and_update(state, now=now)
    assert result.allowed is allowed


def test_windows_are_epoch_aligned() -> None:
    day = 86400
    counter = FixedWindowCounter(limit=1000, window_seconds=day)
    _, result = counter.check_and_update(None, now=day * 3 + 100)
    assert result.reset_after == pytest.approx(day - 100)


def test_skipped_windows_start_fresh() -> None:
    counter = FixedWindowCounter(limit=2, window_seconds=10)
    state, _ = counter.check_and_update(None, now=0, cost=2)
    _, result = counter.check_and_update(state, now=95)
    assert result.allowed
    assert result.remaining == 1


def test_cost_consumes_multiple_and_denies_when_short() -> None:
    counter = FixedWindowCounter(limit=5, window_seconds=10)
    state, result = counter.check_and_update(None, now=0, cost=3)
    assert result.allowed
    assert result.remaining == 2
    new_state, result = counter.check_and_update(state, now=0, cost=3)
    assert not result.allowed
    assert new_state["count"] == 3


def test_cost_above_limit_never_succeeds() -> None:
    _, result = FixedWindowCounter(limit=2, window_seconds=10).check_and_update(None, now=0, cost=3)
    assert not result.allowed
    assert result.retry_after is None


def test_does_not_mutate_input_state() -> None:
    state = {"window": 0, "count": 1}
    snapshot = copy.deepcopy(state)
    new_state, _ = FixedWindowCounter(limit=5, window_seconds=10).check_and_update(state, now=1)
    assert state == snapshot
    assert new_state is not state


@pytest.mark.parametrize(("limit", "window"), [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_config_raises(limit: int, window: float) -> None:
    with pytest.raises(ValueError):
        FixedWindowCounter(limit=limit, window_seconds=window)


@pytest.mark.parametrize("cost", [0, -1])
def test_invalid_cost_raises(cost: int) -> None:
    with pytest.raises(ValueError):
        FixedWindowCounter(limit=1, window_seconds=1).check_and_update(None, now=0, cost=cost)
