import fakeredis
import fakeredis.aioredis
import pytest

from rate_limiter.backends import InMemoryBackend
from rate_limiter.backends.base import RateLimiterBackend
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.core import FixedWindowCounter, TokenBucket
from rate_limiter.core.limiter import RateLimiter


def test_check_admits_until_limit_then_denies() -> None:
    limiter = RateLimiter(FixedWindowCounter(limit=2, window_seconds=10), InMemoryBackend())
    assert limiter.check("a", now=1).allowed
    assert limiter.check("a", now=1).allowed
    denied = limiter.check("a", now=1)
    assert not denied.allowed
    assert denied.retry_after == pytest.approx(9)


def test_keys_are_independent() -> None:
    limiter = RateLimiter(FixedWindowCounter(limit=1, window_seconds=10), InMemoryBackend())
    assert limiter.check("a", now=1).allowed
    assert limiter.check("b", now=1).allowed
    assert not limiter.check("a", now=1).allowed


def test_cost_is_forwarded() -> None:
    limiter = RateLimiter(TokenBucket(rate=1, capacity=5), InMemoryBackend())
    assert limiter.check("a", cost=4, now=0).remaining == 1


def test_key_prefix_namespaces_the_backend_key() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=1, window_seconds=10)
    RateLimiter(algorithm, backend, key_prefix="one").check("k", now=1)
    assert RateLimiter(algorithm, backend, key_prefix="two").check("k", now=1).allowed
    assert not RateLimiter(algorithm, backend, key_prefix="one").check("k", now=1).allowed
    assert not backend.peek("one:k", algorithm, now=1).allowed


def test_default_prefix_is_ratelimit() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=1, window_seconds=10)
    RateLimiter(algorithm, backend).check("k", now=1)
    assert not backend.peek("ratelimit:k", algorithm, now=1).allowed


def test_now_defaults_to_the_current_time(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RateLimiter(FixedWindowCounter(limit=1, window_seconds=10), InMemoryBackend())
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: 5.0)
    assert limiter.check("a").allowed
    assert not limiter.check("a").allowed
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: 10.5)
    assert limiter.check("a").allowed


@pytest.mark.asyncio
async def test_acheck_matches_check() -> None:
    limiter = RateLimiter(FixedWindowCounter(limit=1, window_seconds=10), InMemoryBackend())
    assert (await limiter.acheck("a", now=1)).allowed
    assert not (await limiter.acheck("a", now=1)).allowed


@pytest.mark.asyncio
async def test_acheck_defaults_now_to_the_current_time(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RateLimiter(FixedWindowCounter(limit=1, window_seconds=10), InMemoryBackend())
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: 5.0)
    assert (await limiter.acheck("a")).allowed
    assert not (await limiter.acheck("a")).allowed


def test_works_end_to_end_with_redis_backend() -> None:
    backend: RateLimiterBackend = RedisBackend(fakeredis.FakeRedis())
    limiter = RateLimiter(TokenBucket(rate=1, capacity=2), backend)
    assert limiter.check("a", now=0).allowed
    assert limiter.check("a", now=0).allowed
    assert not limiter.check("a", now=0).allowed
    assert limiter.check("a", now=1).allowed


@pytest.mark.asyncio
async def test_acheck_end_to_end_with_redis_backend() -> None:
    client = fakeredis.aioredis.FakeRedis()
    backend = RedisBackend(fakeredis.FakeRedis(), async_client=client)
    limiter = RateLimiter(TokenBucket(rate=1, capacity=1), backend)
    assert (await limiter.acheck("a", now=0)).allowed
    assert not (await limiter.acheck("a", now=0)).allowed
    await client.aclose()
