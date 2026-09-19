import time

from rate_limiter.backends.base import RateLimiterBackend
from rate_limiter.core.algorithms import Algorithm
from rate_limiter.core.result import RateLimitResult


class RateLimiter:
    """Wires an ``Algorithm`` to a ``RateLimiterBackend``; the object servers and clients hold on to.

    This is the only place the clock is read: ``now`` defaults to ``time.time()`` here so algorithms and
    backends stay deterministic. Pass ``now`` explicitly to test with fabricated timestamps.
    """

    def __init__(
        self, algorithm: Algorithm, backend: RateLimiterBackend, key_prefix: str = "ratelimit"
    ) -> None:
        self.algorithm = algorithm
        self.backend = backend
        self.key_prefix = key_prefix

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    def check(self, key: str, cost: int = 1, now: float | None = None) -> RateLimitResult:
        """Try to consume ``cost`` from ``key``'s allowance and report what happened."""
        return self.backend.increment(
            self._full_key(key), self.algorithm, time.time() if now is None else now, cost
        )

    async def acheck(self, key: str, cost: int = 1, now: float | None = None) -> RateLimitResult:
        """Async ``check``; uses the backend's native async path when it has one."""
        return await self.backend.aincrement(
            self._full_key(key), self.algorithm, time.time() if now is None else now, cost
        )
