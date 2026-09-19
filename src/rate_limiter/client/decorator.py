import functools
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar

from rate_limiter.client._common import (
    ResponseExtractor,
    default_response_extractor,
    local_wait,
    retry_delay,
)
from rate_limiter.client.backoff import RetryPolicy
from rate_limiter.core.limiter import RateLimiter

F = TypeVar("F", bound=Callable[..., Any])


class rate_limited:
    """Pace calls to a third-party API, and back off when it answers 429.

    As a decorator (``@rate_limited(limiter, key="api")``) each call first waits until the local limiter admits
    it (proactive), then, if the returned response is a 429 and a ``retry_policy`` is given, sleeps per the
    policy (honouring ``Retry-After``) and calls again (reactive). After ``max_retries`` the last 429 response
    is returned for the caller to handle.

    As a context manager (``with rate_limited(limiter, key="api"):``) it only does the proactive wait on entry,
    since there is no call to retry.

    ``response_extractor`` maps a return value to ``(status_code, headers)`` or ``None``; the default understands
    ``requests``, ``httpx`` and ``aiohttp`` responses. ``sleep`` can be replaced in tests.
    """

    def __init__(
        self,
        limiter: RateLimiter,
        key: str,
        cost: int = 1,
        retry_policy: RetryPolicy | None = None,
        response_extractor: ResponseExtractor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limiter = limiter
        self.key = key
        self.cost = cost
        self.retry_policy = retry_policy
        self.response_extractor = response_extractor or default_response_extractor
        self._sleep = sleep

    def _acquire(self) -> None:
        while (wait := local_wait(self.limiter.check(self.key, self.cost))) is not None:
            self._sleep(wait)

    def __call__(self, func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                self._acquire()
                response = func(*args, **kwargs)
                delay = retry_delay(response, self.response_extractor, self.retry_policy, attempt)
                if delay is None:
                    return response
                self._sleep(delay)
                attempt += 1

        return wrapper  # type: ignore[return-value]

    def __enter__(self) -> None:
        self._acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
