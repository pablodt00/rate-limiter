"""Rate limiting for servers and for clients of rate-limited APIs.

Everything re-exported here needs only the standard library; the FastAPI, Redis and HTTP-client integrations
live in submodules that import their extras lazily.
"""

from importlib.metadata import PackageNotFoundError, version

from rate_limiter.backends import InMemoryBackend, RateLimiterBackend
from rate_limiter.core import (
    Algorithm,
    FixedWindowCounter,
    RateLimitResult,
    SlidingWindowCounter,
    TokenBucket,
)
from rate_limiter.core.limiter import RateLimiter

try:
    __version__ = version("fastapi-ratelimit-kit")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"

__all__ = [
    "Algorithm",
    "FixedWindowCounter",
    "InMemoryBackend",
    "RateLimitResult",
    "RateLimiter",
    "RateLimiterBackend",
    "SlidingWindowCounter",
    "TokenBucket",
    "__version__",
]
