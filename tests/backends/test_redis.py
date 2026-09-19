import os
from collections.abc import AsyncIterator, Iterator

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio
import redis
import redis.asyncio

from rate_limiter.backends import InMemoryBackend
from rate_limiter.backends.redis import RedisBackend
from rate_limiter.core import Algorithm, FixedWindowCounter, SlidingWindowCounter, TokenBucket

ALGORITHMS: list[Algorithm] = [
    TokenBucket(rate=2, capacity=5),
    FixedWindowCounter(limit=5, window_seconds=10),
    SlidingWindowCounter(limit=5, window_seconds=10),
]
IDS = ["token_bucket", "fixed_window", "sliding_window"]

# (now, cost) sequences that cross window boundaries, refill buckets, deny, and ask for impossible costs.
SEQUENCE = [(0.5, 1), (0.5, 3), (1.0, 1), (1.0, 1), (1.0, 1), (5.0, 2), (9.9, 1), (10.2, 1),
            (10.2, 4), (10.3, 9), (14.0, 1), (19.9, 2), (20.5, 5), (35.0, 1), (100.0, 1)]  # fmt: skip


def _real_redis_url() -> str | None:
    return os.environ.get("RATE_LIMITER_REDIS_URL")


@pytest.fixture(params=["fake", pytest.param("real", marks=pytest.mark.integration)])
def sync_client(request: pytest.FixtureRequest) -> Iterator[redis.Redis]:
    if request.param == "fake":
        yield fakeredis.FakeRedis()
        return
    url = _real_redis_url()
    if url is None:
        pytest.skip("set RATE_LIMITER_REDIS_URL to run against a real Redis")
    client = redis.Redis.from_url(url)
    client.flushdb()
    yield client
    client.flushdb()


@pytest_asyncio.fixture(params=["fake", pytest.param("real", marks=pytest.mark.integration)])
async def async_client(request: pytest.FixtureRequest) -> AsyncIterator[redis.asyncio.Redis]:
    if request.param == "fake":
        client = fakeredis.aioredis.FakeRedis()
    else:
        url = _real_redis_url()
        if url is None:
            pytest.skip("set RATE_LIMITER_REDIS_URL to run against a real Redis")
        client = redis.asyncio.Redis.from_url(url)
        await client.flushdb()
    yield client
    await client.aclose()


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_matches_in_memory_backend(sync_client: redis.Redis, algorithm: Algorithm) -> None:
    """The Lua scripts must agree with the pure Python algorithms on every step."""
    backend = RedisBackend(sync_client)
    reference = InMemoryBackend()
    for now, cost in SEQUENCE:
        actual = backend.increment("k", algorithm, now, cost)
        expected = reference.increment("k", algorithm, now, cost)
        assert actual.allowed == expected.allowed, (now, cost)
        assert actual.remaining == expected.remaining, (now, cost)
        assert actual.limit == expected.limit
        assert actual.reset_after == pytest.approx(expected.reset_after)
        if expected.retry_after is None:
            assert actual.retry_after is None, (now, cost)
        else:
            assert actual.retry_after == pytest.approx(expected.retry_after), (now, cost)


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_peek_matches_and_does_not_consume(sync_client: redis.Redis, algorithm: Algorithm) -> None:
    backend = RedisBackend(sync_client)
    backend.increment("k", algorithm, now=1)
    first = backend.peek("k", algorithm, now=1)
    assert backend.peek("k", algorithm, now=1) == first
    assert first.remaining == 3
    assert backend.increment("k", algorithm, now=1).remaining == 3


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_peek_on_unknown_key_creates_nothing(
    sync_client: redis.Redis, algorithm: Algorithm
) -> None:
    backend = RedisBackend(sync_client)
    backend.peek("k", algorithm, now=1)
    assert sync_client.exists("k") == 0


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_reset_forgets_state(sync_client: redis.Redis, algorithm: Algorithm) -> None:
    backend = RedisBackend(sync_client)
    for _ in range(5):
        backend.increment("k", algorithm, now=1)
    assert not backend.increment("k", algorithm, now=1).allowed
    backend.reset("k")
    assert backend.increment("k", algorithm, now=1).allowed


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_keys_are_independent(sync_client: redis.Redis, algorithm: Algorithm) -> None:
    backend = RedisBackend(sync_client)
    for _ in range(5):
        backend.increment("a", algorithm, now=1)
    assert not backend.increment("a", algorithm, now=1).allowed
    assert backend.increment("b", algorithm, now=1).allowed


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
def test_state_key_gets_a_ttl(sync_client: redis.Redis, algorithm: Algorithm) -> None:
    RedisBackend(sync_client).increment("k", algorithm, now=1)
    ttl = sync_client.pttl("k")
    assert 0 < ttl <= 20_000  # two window lengths (token bucket: 2 * 5 / 2 = 5s)


def test_unsupported_algorithm_is_rejected(sync_client: redis.Redis) -> None:
    class Custom:
        def check_and_update(self, state, now, cost=1):  # type: ignore[no-untyped-def]
            raise AssertionError("must not be called")

    with pytest.raises(TypeError, match="Custom"):
        RedisBackend(sync_client).increment("k", Custom(), now=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=IDS)
async def test_aincrement_matches_in_memory_backend(
    async_client: redis.asyncio.Redis, algorithm: Algorithm
) -> None:
    backend = RedisBackend(fakeredis.FakeRedis(), async_client=async_client)
    reference = InMemoryBackend()
    for now, cost in SEQUENCE:
        actual = await backend.aincrement("k", algorithm, now, cost)
        expected = reference.increment("k", algorithm, now, cost)
        assert actual.allowed == expected.allowed, (now, cost)
        assert actual.remaining == expected.remaining, (now, cost)
        assert actual.reset_after == pytest.approx(expected.reset_after)
        if expected.retry_after is None:
            assert actual.retry_after is None
        else:
            assert actual.retry_after == pytest.approx(expected.retry_after)


@pytest.mark.asyncio
async def test_aincrement_without_async_client_raises() -> None:
    backend = RedisBackend(fakeredis.FakeRedis())
    with pytest.raises(RuntimeError, match="async_client"):
        await backend.aincrement("k", FixedWindowCounter(limit=1, window_seconds=1), now=1)
