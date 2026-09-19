import asyncio
import threading

import pytest

from rate_limiter.backends import InMemoryBackend
from rate_limiter.core import Algorithm, FixedWindowCounter, SlidingWindowCounter, TokenBucket

ALGORITHMS: list[Algorithm] = [
    TokenBucket(rate=1, capacity=5),
    FixedWindowCounter(limit=5, window_seconds=10),
    SlidingWindowCounter(limit=5, window_seconds=10),
]


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_allows_up_to_limit_then_denies(algorithm: Algorithm) -> None:
    backend = InMemoryBackend()
    results = [backend.increment("k", algorithm, now=1) for _ in range(6)]
    assert [r.allowed for r in results] == [True] * 5 + [False]


def test_keys_are_independent() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=1, window_seconds=10)
    assert backend.increment("a", algorithm, now=1).allowed
    assert not backend.increment("a", algorithm, now=1).allowed
    assert backend.increment("b", algorithm, now=1).allowed


def test_cost_is_forwarded() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=5, window_seconds=10)
    assert backend.increment("k", algorithm, now=1, cost=5).allowed
    assert not backend.increment("k", algorithm, now=1).allowed


def test_reset_forgets_state() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=1, window_seconds=10)
    backend.increment("k", algorithm, now=1)
    backend.reset("k")
    assert backend.increment("k", algorithm, now=1).allowed


def test_reset_unknown_key_is_a_noop() -> None:
    InMemoryBackend().reset("never-seen")


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_peek_does_not_consume(algorithm: Algorithm) -> None:
    backend = InMemoryBackend()
    backend.increment("k", algorithm, now=1)
    first = backend.peek("k", algorithm, now=1)
    second = backend.peek("k", algorithm, now=1)
    assert first == second
    # peek shows the outcome of the next request (3 left after it); the real request then sees the same.
    assert first.remaining == 3
    assert backend.increment("k", algorithm, now=1).remaining == 3


def test_peek_on_unknown_key_does_not_create_state() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=2, window_seconds=10)
    assert backend.peek("k", algorithm, now=1).remaining == 1
    assert backend.increment("k", algorithm, now=1).remaining == 1


def test_aincrement_delegates_to_increment() -> None:
    backend = InMemoryBackend()
    algorithm = FixedWindowCounter(limit=1, window_seconds=10)
    assert asyncio.run(backend.aincrement("k", algorithm, now=1)).allowed
    assert not asyncio.run(backend.aincrement("k", algorithm, now=1)).allowed


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_concurrent_increments_never_exceed_allowance(algorithm: Algorithm) -> None:
    """Many threads race on one key at a frozen time; exactly the allowance (5) may be admitted."""
    backend = InMemoryBackend()
    threads_count, attempts_each = 16, 50
    admitted: list[int] = [0] * threads_count
    barrier = threading.Barrier(threads_count)

    def worker(index: int) -> None:
        barrier.wait()
        for _ in range(attempts_each):
            if backend.increment("hot", algorithm, now=1).allowed:
                admitted[index] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(admitted) == 5
