"""Redis backend (optional extra: ``fastapi-ratelimit-kit[redis]``).

Each algorithm is re-implemented as a Lua script so the whole load-decide-persist step runs atomically inside
Redis (``MULTI``/``EXEC`` cannot express read-then-conditionally-write without a slow ``WATCH`` retry loop).
The scripts mirror ``core/algorithms.py`` and must be kept in sync with it. The ``redis`` package is never
imported here; the caller passes in already-constructed clients, so a bare ``import rate_limiter`` is unaffected.
"""

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rate_limiter.backends.base import RateLimiterBackend
from rate_limiter.core.algorithms import (
    Algorithm,
    FixedWindowCounter,
    SlidingWindowCounter,
    TokenBucket,
)
from rate_limiter.core.result import RateLimitResult

if TYPE_CHECKING:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis

# Every script takes KEYS[1] = state key and ARGV = now, cost, commit ("1" persists, "0" is read-only),
# ttl_ms, then the algorithm's own config. It returns {allowed, remaining, limit, reset_after, retry_after}
# with the floats as strings (Redis would truncate Lua numbers to integers); retry_after is "" for "never".
_PRELUDE = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local commit = ARGV[3] == '1'
local ttl_ms = tonumber(ARGV[4])
local function fmt(x) return string.format('%.17g', x) end
"""

_TOKEN_BUCKET = (
    _PRELUDE
    + """
local rate = tonumber(ARGV[5])
local capacity = tonumber(ARGV[6])
local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens
if data[1] then
  local elapsed = math.max(0, now - tonumber(data[2]))
  tokens = math.min(capacity, tonumber(data[1]) + elapsed * rate)
else
  tokens = capacity
end
local allowed = cost <= tokens
if allowed then tokens = tokens - cost end
local retry_after = ''
if (not allowed) and cost <= capacity then retry_after = fmt((cost - tokens) / rate) end
if commit then
  redis.call('HSET', key, 'tokens', fmt(tokens), 'last_refill', fmt(now))
  redis.call('PEXPIRE', key, ttl_ms)
end
return {allowed and 1 or 0, math.floor(tokens), capacity, fmt((capacity - tokens) / rate), retry_after}
"""
)

_FIXED_WINDOW = (
    _PRELUDE
    + """
local limit = tonumber(ARGV[5])
local ws = tonumber(ARGV[6])
local window = math.floor(now / ws)
local data = redis.call('HMGET', key, 'window', 'count')
local count = 0
if data[1] and tonumber(data[1]) == window then count = tonumber(data[2]) end
local allowed = count + cost <= limit
if allowed then count = count + cost end
local reset_after = (window + 1) * ws - now
local retry_after = ''
if (not allowed) and cost <= limit then retry_after = fmt(reset_after) end
if commit then
  redis.call('HSET', key, 'window', window, 'count', count)
  redis.call('PEXPIRE', key, ttl_ms)
end
return {allowed and 1 or 0, limit - count, limit, fmt(reset_after), retry_after}
"""
)

_SLIDING_WINDOW = (
    _PRELUDE
    + """
local limit = tonumber(ARGV[5])
local ws = tonumber(ARGV[6])
local window = math.floor(now / ws)
local data = redis.call('HMGET', key, 'window', 'current', 'previous')
local current, previous = 0, 0
if data[1] then
  local stored = tonumber(data[1])
  if stored == window then
    current, previous = tonumber(data[2]), tonumber(data[3])
  elseif stored == window - 1 then
    current, previous = 0, tonumber(data[2])
  end
end
local elapsed = now - window * ws
local estimated = previous * (1 - elapsed / ws) + current
local allowed = estimated + cost <= limit
if allowed then
  current = current + cost
  estimated = estimated + cost
end
local retry_after = ''
if (not allowed) and cost <= limit then
  local time_to_next = ws - elapsed
  local wait
  if previous > 0 and current + cost <= limit then
    local needed = 1 - (limit - current - cost) / previous
    wait = math.max(0, needed * ws - elapsed)
  elseif current == 0 then
    wait = time_to_next
  else
    local needed = math.min(1, math.max(0, 1 - (limit - cost) / current))
    wait = time_to_next + needed * ws
  end
  retry_after = fmt(wait)
end
local reset_after = (ws - elapsed) + (current > 0 and ws or 0)
if commit then
  redis.call('HSET', key, 'window', window, 'current', current, 'previous', previous)
  redis.call('PEXPIRE', key, ttl_ms)
end
return {allowed and 1 or 0, math.max(0, math.floor(limit - estimated)), limit, fmt(reset_after), retry_after}
"""
)


def _ttl_ms(seconds: float) -> int:
    return max(1, math.ceil(seconds * 1000))


def _token_bucket_config(algorithm: TokenBucket) -> tuple[list[float], int]:
    # Long enough for an empty bucket to refill completely, twice over.
    return [algorithm.rate, algorithm.capacity], _ttl_ms(2 * algorithm.capacity / algorithm.rate)


def _window_config(algorithm: FixedWindowCounter | SlidingWindowCounter) -> tuple[list[float], int]:
    # A couple of window lengths, so a key survives long enough to be seen as the "previous" window.
    return [algorithm.limit, algorithm.window_seconds], _ttl_ms(2 * algorithm.window_seconds)


_SCRIPTS: dict[type, str] = {
    TokenBucket: _TOKEN_BUCKET,
    FixedWindowCounter: _FIXED_WINDOW,
    SlidingWindowCounter: _SLIDING_WINDOW,
}
_CONFIGS: dict[type, Callable[[Any], tuple[list[float], int]]] = {
    TokenBucket: _token_bucket_config,
    FixedWindowCounter: _window_config,
    SlidingWindowCounter: _window_config,
}


def _to_result(raw: list[Any]) -> RateLimitResult:
    def text(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)

    retry_after = text(raw[4])
    return RateLimitResult(
        allowed=int(raw[0]) == 1,
        remaining=int(raw[1]),
        limit=int(raw[2]),
        reset_after=float(text(raw[3])),
        retry_after=float(retry_after) if retry_after else None,
    )


class RedisBackend(RateLimiterBackend):
    """Backend that keeps state in Redis hashes, one atomic Lua call per request.

    ``client`` is a ``redis.Redis`` used by the sync methods. ``async_client`` is an optional
    ``redis.asyncio.Redis`` used by ``aincrement`` (a true async path, no thread hop). State keys expire after
    a couple of window lengths so abandoned per-user or per-IP keys do not leak.
    """

    def __init__(self, client: "Redis", async_client: "AsyncRedis | None" = None) -> None:
        self._client = client
        self._async_client = async_client
        self._scripts = {kind: client.register_script(lua) for kind, lua in _SCRIPTS.items()}
        self._async_scripts = (
            {kind: async_client.register_script(lua) for kind, lua in _SCRIPTS.items()}
            if async_client is not None
            else {}
        )

    @staticmethod
    def _args(algorithm: Algorithm, now: float, cost: int, commit: bool) -> list[Any]:
        kind = type(algorithm)
        if kind not in _CONFIGS:
            raise TypeError(f"RedisBackend does not support {kind.__name__}")
        config, ttl_ms = _CONFIGS[kind](algorithm)
        return [repr(now), cost, int(commit), ttl_ms, *config]

    def increment(
        self, key: str, algorithm: Algorithm, now: float, cost: int = 1
    ) -> RateLimitResult:
        args = self._args(algorithm, now, cost, commit=True)
        return _to_result(self._scripts[type(algorithm)](keys=[key], args=args))

    async def aincrement(
        self, key: str, algorithm: Algorithm, now: float, cost: int = 1
    ) -> RateLimitResult:
        if self._async_client is None:
            raise RuntimeError(
                "aincrement requires RedisBackend(..., async_client=redis.asyncio.Redis)"
            )
        args = self._args(algorithm, now, cost, commit=True)
        raw = await self._async_scripts[type(algorithm)](keys=[key], args=args)
        return _to_result(raw)

    def reset(self, key: str) -> None:
        self._client.delete(key)

    def peek(self, key: str, algorithm: Algorithm, now: float) -> RateLimitResult:
        args = self._args(algorithm, now, 1, commit=False)
        return _to_result(self._scripts[type(algorithm)](keys=[key], args=args))
