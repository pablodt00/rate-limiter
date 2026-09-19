import copy

import pytest

from rate_limiter.core import SlidingWindowCounter


def test_allows_until_limit_then_denies() -> None:
    counter = SlidingWindowCounter(limit=3, window_seconds=10)
    state = None
    for expected_remaining in (2, 1, 0):
        state, result = counter.check_and_update(state, now=1)
        assert result.allowed
        assert result.remaining == expected_remaining
    _, result = counter.check_and_update(state, now=1)
    assert not result.allowed
    assert result.retry_after is not None


def test_request_exactly_at_boundary_counts_previous_fully() -> None:
    counter = SlidingWindowCounter(limit=2, window_seconds=10)
    state, _ = counter.check_and_update(None, now=5, cost=2)
    # At t=10 the new window starts and the previous window still has weight 1.0.
    _, result = counter.check_and_update(state, now=10)
    assert not result.allowed


def test_previous_window_is_weighted_by_overlap() -> None:
    counter = SlidingWindowCounter(limit=10, window_seconds=10)
    state, _ = counter.check_and_update(None, now=5, cost=10)
    # Halfway through the next window: 10 * 0.5 = 5 counted, so 5 more fit.
    _, allowed = counter.check_and_update(state, now=15, cost=5)
    assert allowed.allowed
    _, denied = counter.check_and_update(state, now=15, cost=6)
    assert not denied.allowed


def test_gap_of_more_than_one_window_resets() -> None:
    counter = SlidingWindowCounter(limit=2, window_seconds=10)
    state, _ = counter.check_and_update(None, now=0, cost=2)
    _, result = counter.check_and_update(state, now=35)
    assert result.allowed
    assert result.remaining == 1


def test_cost_above_limit_never_succeeds() -> None:
    _, result = SlidingWindowCounter(limit=2, window_seconds=10).check_and_update(
        None, now=0, cost=3
    )
    assert not result.allowed
    assert result.retry_after is None


@pytest.mark.parametrize(
    ("state", "now", "cost"),
    [
        # Blocked by the previous window decaying inside the current window.
        ({"window": 1, "current": 2, "previous": 8}, 10.5, 1),
        # Blocked by the current window's own count: must wait for the next window.
        ({"window": 0, "current": 5, "previous": 0}, 3, 1),
        ({"window": 0, "current": 5, "previous": 0}, 3, 3),
        ({"window": 1, "current": 9, "previous": 4}, 12, 2),
    ],
)
def test_retry_after_is_exact(state: dict[str, int], now: float, cost: int) -> None:
    counter = SlidingWindowCounter(limit=5 if state["window"] == 0 else 10, window_seconds=10)
    _, denied = counter.check_and_update(state, now=now, cost=cost)
    assert not denied.allowed
    assert denied.retry_after is not None
    at_retry = now + denied.retry_after
    _, ok = counter.check_and_update(state, now=at_retry + 1e-9, cost=cost)
    assert ok.allowed
    _, too_early = counter.check_and_update(state, now=at_retry - 1e-3, cost=cost)
    assert not too_early.allowed


def test_admitted_never_exceeds_limit_over_a_steady_stream() -> None:
    limit, window = 10, 10.0
    counter = SlidingWindowCounter(limit=limit, window_seconds=window)
    state = None
    admitted: list[float] = []
    for step in range(400):
        now = step * 0.5
        state, result = counter.check_and_update(state, now=now)
        if result.allowed:
            admitted.append(now)
    # Any window-length slice may exceed the limit only by the approximation's bound (< 2x).
    for start in admitted:
        in_window = [t for t in admitted if start <= t < start + window]
        assert len(in_window) <= limit * 2


def test_does_not_mutate_input_state() -> None:
    state = {"window": 0, "current": 1, "previous": 0}
    snapshot = copy.deepcopy(state)
    new_state, _ = SlidingWindowCounter(limit=5, window_seconds=10).check_and_update(state, now=1)
    assert state == snapshot
    assert new_state is not state


@pytest.mark.parametrize(("limit", "window"), [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_config_raises(limit: int, window: float) -> None:
    with pytest.raises(ValueError):
        SlidingWindowCounter(limit=limit, window_seconds=window)


@pytest.mark.parametrize("cost", [0, -1])
def test_invalid_cost_raises(cost: int) -> None:
    with pytest.raises(ValueError):
        SlidingWindowCounter(limit=1, window_seconds=1).check_and_update(None, now=0, cost=cost)
