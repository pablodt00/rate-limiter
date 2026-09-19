import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

# Reset values above this are treated as absolute epoch seconds rather than "seconds from now".
_EPOCH_THRESHOLD = 1_000_000_000
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


@dataclass(frozen=True)
class ParsedRateLimitInfo:
    """What a server told us about its limits. Every field is ``None`` when the server did not say."""

    limit: int | None = None
    remaining: int | None = None
    reset_after: float | None = None  # seconds from now until the quota refreshes
    retry_after: float | None = None  # seconds to wait before retrying, from ``Retry-After``


# Header-name aliases per field, lowercase, tried in order. Extend with ``register_header_aliases``.
_ALIASES: dict[str, list[str]] = {
    "limit": ["x-ratelimit-limit", "ratelimit-limit", "x-rate-limit-limit"],
    "remaining": ["x-ratelimit-remaining", "ratelimit-remaining", "x-rate-limit-remaining"],
    "reset": ["x-ratelimit-reset", "ratelimit-reset", "x-rate-limit-reset"],
}


def register_header_aliases(field: str, *names: str) -> None:
    """Teach the parser extra header names for ``field`` ("limit", "remaining" or "reset").

    Later registrations are tried before the built-in names, so a vendor can override the defaults.
    """
    if field not in _ALIASES:
        raise ValueError(f"unknown field {field!r}; expected one of {sorted(_ALIASES)}")
    _ALIASES[field] = [n.lower() for n in names] + _ALIASES[field]


# OpenAI-style headers carry the unit in the name and durations like "6m0s" in the reset value.
register_header_aliases("limit", "x-ratelimit-limit-requests")
register_header_aliases("remaining", "x-ratelimit-remaining-requests")
register_header_aliases("reset", "x-ratelimit-reset-requests")


def _lowered(headers: Mapping[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def _parse_duration(value: str) -> float | None:
    """Parse durations such as ``"1.5"``, ``"20ms"`` or ``"6m0s"`` into seconds."""
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(value)
    if not parts or "".join(n + u for n, u in parts) != value:
        return None
    return sum(float(n) * _UNIT_SECONDS[u] for n, u in parts)


def parse_retry_after(headers: Mapping[str, str], now: float | None = None) -> float | None:
    """Seconds to wait according to ``Retry-After`` (delta-seconds or HTTP-date, RFC 9110), else ``None``."""
    value = _lowered(headers).get("retry-after")
    if value is None:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - (time.time() if now is None else now)
    return max(0.0, seconds)


def _first(lowered: dict[str, str], field: str) -> str | None:
    for name in _ALIASES[field]:
        if name in lowered:
            return lowered[name]
    return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_rate_limit_headers(
    headers: Mapping[str, str], now: float | None = None
) -> ParsedRateLimitInfo:
    """Extract limit, remaining, reset and retry-after from response headers, whatever the vendor."""
    lowered = _lowered(headers)
    reset_raw = _first(lowered, "reset")
    reset = _parse_duration(reset_raw) if reset_raw is not None else None
    if reset is not None and reset > _EPOCH_THRESHOLD:
        reset -= time.time() if now is None else now
    return ParsedRateLimitInfo(
        limit=_to_int(_first(lowered, "limit")),
        remaining=_to_int(_first(lowered, "remaining")),
        reset_after=None if reset is None else max(0.0, reset),
        retry_after=parse_retry_after(headers, now),
    )
