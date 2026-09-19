from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server._headers import rate_limit_headers, retry_headers
from rate_limiter.server.keys import KeyFunc, by_ip, resolve_key

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RateLimitMiddleware:
    """Rate limit every HTTP request to an app; add it with ``app.add_middleware(RateLimitMiddleware, ...)``.

    Written as raw ASGI on purpose: ``BaseHTTPMiddleware`` has known problems with streaming responses and
    background tasks. Allowed requests get ``X-RateLimit-*`` headers added on the way out (headers a route's
    own ``rate_limit()`` dependency already set are kept, since they are the more specific ones); denied
    requests get a JSON 429 with ``Retry-After`` and never reach the app. Paths in ``exempt_paths`` and
    non-HTTP traffic (websockets, lifespan) pass through untouched.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        limiter: RateLimiter,
        key_func: KeyFunc = by_ip,
        cost: int = 1,
        exempt_paths: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.key_func = key_func
        self.cost = cost
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import MutableHeaders  # lazy: optional extra
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        key = await resolve_key(self.key_func, Request(scope))
        result = await self.limiter.acheck(key, cost=self.cost)
        if not result.allowed:
            response = JSONResponse(
                {"detail": "Rate limit exceeded"}, status_code=429, headers=retry_headers(result)
            )
            await response(scope, receive, send)
            return

        headers = rate_limit_headers(result)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
