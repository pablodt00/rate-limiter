import asyncio
import functools
from collections.abc import Awaitable, Callable
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

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class async_rate_limited:
    """Async twin of ``rate_limited``, for ``async def`` callables and ``async with`` blocks.

    Waits with ``limiter.acheck`` and ``asyncio.sleep`` so the event loop keeps running. Retries a 429 per
    ``retry_policy`` exactly like the sync version; the default ``response_extractor`` understands ``httpx``
    and ``aiohttp`` responses. ``sleep`` can be replaced in tests.
    """

    def __init__(
        self,
        limiter: RateLimiter,
        key: str,
        cost: int = 1,
        retry_policy: RetryPolicy | None = None,
        response_extractor: ResponseExtractor | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limiter = limiter
        self.key = key
        self.cost = cost
        self.retry_policy = retry_policy
        self.response_extractor = response_extractor or default_response_extractor
        self._sleep = sleep

    async def _acquire(self) -> None:
        while (wait := local_wait(await self.limiter.acheck(self.key, self.cost))) is not None:
            await self._sleep(wait)

    def __call__(self, func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                await self._acquire()
                response = await func(*args, **kwargs)
                delay = retry_delay(response, self.response_extractor, self.retry_policy, attempt)
                if delay is None:
                    return response
                await self._sleep(delay)
                attempt += 1

        return wrapper  # type: ignore[return-value]

    async def __aenter__(self) -> None:
        await self._acquire()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
