"""The response-header contract shared by the dependency and the middleware."""

import math

from rate_limiter.core.result import RateLimitResult


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    """``X-RateLimit-Limit/Remaining/Reset`` for any response; reset is whole seconds from now."""
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(math.ceil(result.reset_after)),
    }


def retry_headers(result: RateLimitResult) -> dict[str, str]:
    """Headers for a denied request: the usual ones plus ``Retry-After`` when a retry could ever succeed."""
    headers = rate_limit_headers(result)
    if result.retry_after is not None:
        headers["Retry-After"] = str(math.ceil(result.retry_after))
    return headers
