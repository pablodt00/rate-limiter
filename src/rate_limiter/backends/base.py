from abc import ABC, abstractmethod

from rate_limiter.core.algorithms import Algorithm
from rate_limiter.core.result import RateLimitResult


class RateLimiterBackend(ABC):
    """Stores per-key state and applies an algorithm to it atomically.

    The backend receives the ``Algorithm`` itself, so each algorithm's state shape stays opaque to it. It owns
    the atomic load-update-persist step per key; race-safety lives here, not in the algorithms.
    """

    @abstractmethod
    def increment(
        self, key: str, algorithm: Algorithm, now: float, cost: int = 1
    ) -> RateLimitResult:
        """Atomically apply ``algorithm`` to ``key``'s state, persist the new state and return the result."""

    async def aincrement(
        self, key: str, algorithm: Algorithm, now: float, cost: int = 1
    ) -> RateLimitResult:
        """Async ``increment``. Delegates to the sync one; backends with native async should override."""
        return self.increment(key, algorithm, now, cost)

    @abstractmethod
    def reset(self, key: str) -> None:
        """Forget ``key``'s state, so its next request starts fresh."""

    @abstractmethod
    def peek(self, key: str, algorithm: Algorithm, now: float) -> RateLimitResult:
        """Return what a request costing 1 would see, without consuming anything or persisting state."""
