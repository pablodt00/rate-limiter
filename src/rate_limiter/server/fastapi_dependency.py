from collections.abc import Awaitable, Callable

from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server._headers import rate_limit_headers, retry_headers
from rate_limiter.server.keys import KeyFunc, by_ip, resolve_key


def rate_limit(
    limiter: RateLimiter, key_func: KeyFunc = by_ip, cost: int = 1
) -> Callable[..., Awaitable[None]]:
    """A FastAPI dependency that rate limits a route: ``Depends(rate_limit(limiter))``.

    Adds ``X-RateLimit-*`` headers to every response and raises 429 with ``Retry-After`` once the caller is
    over their allowance.
    """
    from fastapi import HTTPException, Request, Response  # lazy: fastapi is an optional extra

    async def dependency(request: Request, response: Response) -> None:
        result = await limiter.acheck(await resolve_key(key_func, request), cost=cost)
        if not result.allowed:
            raise HTTPException(
                status_code=429, detail="Rate limit exceeded", headers=retry_headers(result)
            )
        response.headers.update(rate_limit_headers(result))

    return dependency
