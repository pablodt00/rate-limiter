import random
from collections.abc import Callable
from dataclasses import dataclass, field

from rate_limiter.client.headers import ParsedRateLimitInfo


@dataclass
class RetryPolicy:
    """How long to wait before retrying a rate-limited call, and how many times to try.

    Delays grow exponentially (``base_delay * 2 ** attempt``), are capped at ``max_delay`` and, with
    ``jitter``, are drawn uniformly from ``[0, that value]`` ("full jitter") so clients do not retry in
    lockstep. A server-provided ``Retry-After`` replaces the computed delay when ``respect_retry_after`` is set.
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: bool = True
    respect_retry_after: bool = True
    # Source of randomness in [0, 1); replace in tests for deterministic delays.
    random_func: Callable[[], float] = field(default=random.random, repr=False, compare=False)

    def compute_delay(self, attempt: int, parsed: ParsedRateLimitInfo | None = None) -> float:
        """Seconds to sleep before retry number ``attempt`` (0 for the first retry)."""
        if self.respect_retry_after and parsed is not None and parsed.retry_after is not None:
            return parsed.retry_after
        # Clamp the exponent so a huge attempt count cannot overflow a float.
        ceiling = min(self.max_delay, self.base_delay * float(2 ** min(attempt, 62)))
        return ceiling * self.random_func() if self.jitter else ceiling


def is_rate_limited_response(status_code: int) -> bool:
    """Whether ``status_code`` means "slow down": 429 Too Many Requests."""
    return status_code == 429
