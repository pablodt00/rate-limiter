import math
from dataclasses import dataclass
from typing import Any, Protocol

from rate_limiter.core.result import RateLimitResult

State = dict[str, Any]


class Algorithm(Protocol):
    """A pure rate-limiting algorithm.

    Takes the previous state (``None`` for a key never seen), the current time and a cost, and returns the
    new state plus the result. Implementations never read the clock and never mutate ``state``.
    """

    def check_and_update(
        self, state: State | None, now: float, cost: int = 1
    ) -> tuple[State, RateLimitResult]: ...


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


def _check_cost(cost: int) -> None:
    if cost < 1:
        raise ValueError(f"cost must be >= 1, got {cost}")


@dataclass(frozen=True)
class TokenBucket:
    """Bucket refilled at ``rate`` tokens per second, holding at most ``capacity`` tokens.

    State: ``{"tokens": float, "last_refill": float}``. A new bucket starts full.
    """

    rate: float
    capacity: int

    def __post_init__(self) -> None:
        _positive("rate", self.rate)
        _positive("capacity", self.capacity)

    def check_and_update(
        self, state: State | None, now: float, cost: int = 1
    ) -> tuple[State, RateLimitResult]:
        _check_cost(cost)
        if state is None:
            tokens = float(self.capacity)
        else:
            elapsed = max(0.0, now - state["last_refill"])
            tokens = min(float(self.capacity), state["tokens"] + elapsed * self.rate)

        allowed = cost <= tokens
        if allowed:
            tokens -= cost

        retry_after: float | None = None
        if not allowed and cost <= self.capacity:
            retry_after = (cost - tokens) / self.rate

        result = RateLimitResult(
            allowed=allowed,
            remaining=math.floor(tokens),
            limit=self.capacity,
            reset_after=(self.capacity - tokens) / self.rate,
            retry_after=retry_after,
        )
        return {"tokens": tokens, "last_refill": now}, result


@dataclass(frozen=True)
class FixedWindowCounter:
    """At most ``limit`` cost per epoch-aligned window of ``window_seconds``.

    Windows are aligned to the epoch, so a one-day window resets at midnight UTC.
    State: ``{"window": int, "count": int}``.
    """

    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        _positive("limit", self.limit)
        _positive("window_seconds", self.window_seconds)

    def check_and_update(
        self, state: State | None, now: float, cost: int = 1
    ) -> tuple[State, RateLimitResult]:
        _check_cost(cost)
        window = math.floor(now / self.window_seconds)
        count = state["count"] if state is not None and state["window"] == window else 0

        allowed = count + cost <= self.limit
        if allowed:
            count += cost

        reset_after = (window + 1) * self.window_seconds - now
        result = RateLimitResult(
            allowed=allowed,
            remaining=self.limit - count,
            limit=self.limit,
            reset_after=reset_after,
            retry_after=None if allowed or cost > self.limit else reset_after,
        )
        return {"window": window, "count": count}, result


@dataclass(frozen=True)
class SlidingWindowCounter:
    """Approximated sliding window using two counters, so state stays O(1).

    The previous window's count is weighted by how much of it still overlaps the sliding window ending at
    ``now``. State: ``{"window": int, "current": int, "previous": int}``.
    """

    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        _positive("limit", self.limit)
        _positive("window_seconds", self.window_seconds)

    def check_and_update(
        self, state: State | None, now: float, cost: int = 1
    ) -> tuple[State, RateLimitResult]:
        _check_cost(cost)
        ws = self.window_seconds
        window = math.floor(now / ws)
        current, previous = self._roll(state, window)

        elapsed = now - window * ws
        estimated = previous * (1 - elapsed / ws) + current

        allowed = estimated + cost <= self.limit
        if allowed:
            current += cost
            estimated += cost

        retry_after: float | None = None
        if not allowed and cost <= self.limit:
            retry_after = self._retry_after(current, previous, cost, elapsed)

        time_to_next = ws - elapsed
        result = RateLimitResult(
            allowed=allowed,
            remaining=max(0, math.floor(self.limit - estimated)),
            limit=self.limit,
            reset_after=time_to_next + (ws if current > 0 else 0.0),
            retry_after=retry_after,
        )
        return {"window": window, "current": current, "previous": previous}, result

    @staticmethod
    def _roll(state: State | None, window: int) -> tuple[int, int]:
        """Return ``(current, previous)`` counts as seen from ``window``."""
        if state is None:
            return 0, 0
        if state["window"] == window:
            return state["current"], state["previous"]
        if state["window"] == window - 1:
            return 0, state["current"]
        return 0, 0

    def _retry_after(self, current: int, previous: int, cost: int, elapsed: float) -> float:
        """Seconds until ``cost`` fits, solving the weighted estimate exactly."""
        ws = self.window_seconds
        if previous > 0 and current + cost <= self.limit:
            # Wait for the previous window's weight to decay within this window.
            needed_fraction = 1 - (self.limit - current - cost) / previous
            return max(0.0, needed_fraction * ws - elapsed)
        # Wait for the next window, where this count becomes the (decaying) previous count. ``current`` is
        # positive here: with nothing counted in this window the request would have been allowed.
        time_to_next = ws - elapsed
        needed_fraction = min(1.0, max(0.0, 1 - (self.limit - cost) / current))
        return time_to_next + needed_fraction * ws
