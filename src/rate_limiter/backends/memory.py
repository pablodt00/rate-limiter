import copy
import threading

from rate_limiter.backends.base import RateLimiterBackend
from rate_limiter.core.algorithms import Algorithm, State
from rate_limiter.core.result import RateLimitResult


class InMemoryBackend(RateLimiterBackend):
    """Process-local backend using only the standard library.

    A single ``threading.Lock`` guards all keys, so every ``increment`` is atomic. That also serializes
    unrelated keys: an intentional v1 simplification that is fine for a single process or script. Use the
    Redis backend for higher concurrency or several processes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, State] = {}

    def increment(
        self, key: str, algorithm: Algorithm, now: float, cost: int = 1
    ) -> RateLimitResult:
        with self._lock:
            new_state, result = algorithm.check_and_update(self._states.get(key), now, cost)
            self._states[key] = new_state
            return result

    def reset(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def peek(self, key: str, algorithm: Algorithm, now: float) -> RateLimitResult:
        with self._lock:
            state = self._states.get(key)
            _, result = algorithm.check_and_update(copy.deepcopy(state), now, 1)
            return result
