from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a rate-limit check, returned by every algorithm and backend.

    ``reset_after`` is the number of seconds until the limiter is back to its full allowance.
    ``retry_after`` is the number of seconds until this request would succeed; it is ``None`` when the
    request was allowed, or when it can never succeed (its cost exceeds the limit).
    """

    allowed: bool
    remaining: int
    limit: int
    reset_after: float
    retry_after: float | None
