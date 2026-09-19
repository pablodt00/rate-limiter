"""Pieces shared by the sync and async decorators."""

from collections.abc import Callable, Mapping
from typing import Any

from rate_limiter.client.backoff import RetryPolicy, is_rate_limited_response
from rate_limiter.client.headers import ParsedRateLimitInfo, parse_rate_limit_headers
from rate_limiter.core.result import RateLimitResult

# Turns whatever the wrapped call returned into ``(status_code, headers)``, or ``None`` if it is not a response.
ResponseExtractor = Callable[[Any], "tuple[int, Mapping[str, str]] | None"]


class RateLimitExceeded(Exception):
    """A request can never be admitted locally, e.g. its cost is above the limiter's capacity."""


def default_response_extractor(response: Any) -> tuple[int, Mapping[str, str]] | None:
    """Understands ``requests``, ``httpx`` (``status_code``) and ``aiohttp`` (``status``) responses."""
    headers = getattr(response, "headers", None)
    status = getattr(response, "status_code", getattr(response, "status", None))
    if headers is None or not isinstance(status, int):
        return None
    return status, headers


def local_wait(result: RateLimitResult) -> float | None:
    """Seconds to wait before retrying a denied local check; raises if it can never succeed."""
    if result.allowed:
        return None
    if result.retry_after is None:
        raise RateLimitExceeded("request cost exceeds what the rate limiter can ever admit")
    return result.retry_after


def retry_delay(
    response: Any,
    extractor: ResponseExtractor,
    policy: RetryPolicy | None,
    attempt: int,
) -> float | None:
    """How long to sleep before retrying ``response``, or ``None`` if it should be returned as is."""
    if policy is None or attempt >= policy.max_retries:
        return None
    extracted = extractor(response)
    if extracted is None or not is_rate_limited_response(extracted[0]):
        return None
    parsed: ParsedRateLimitInfo = parse_rate_limit_headers(extracted[1])
    return policy.compute_delay(attempt, parsed)
