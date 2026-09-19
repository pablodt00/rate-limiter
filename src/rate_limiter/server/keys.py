"""Ways to decide *who* a request belongs to, so each caller gets their own allowance.

A key function is any callable taking a request and returning a string (or an awaitable of one); the helpers
here are just the common ones, and your own functions of the same shape plug in the same way.
"""

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

KeyFunc = Callable[["Request"], "str | Awaitable[str]"]


def by_ip(request: "Request") -> str:
    """The client's IP address. Behind a proxy, configure it to forward the real client address."""
    return request.client.host if request.client else "unknown"


def by_header(header_name: str) -> KeyFunc:
    """Key on the value of ``header_name`` (e.g. an API key). Requests without it share one bucket."""

    def key_func(request: "Request") -> str:
        return f"{header_name.lower()}:{request.headers.get(header_name, '')}"

    return key_func


def by_route(request: "Request") -> str:
    """The HTTP method and route, using the route template (``/items/{id}``) when routing already ran.

    Inside a middleware routing has not happened yet, so the concrete request path is used instead.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return f"{request.method}:{path}"


def combine(*key_funcs: KeyFunc) -> KeyFunc:
    """Join several key functions, e.g. ``combine(by_ip, by_route)`` for a per-IP, per-route allowance."""
    if not key_funcs:
        raise ValueError("combine() needs at least one key function")

    async def key_func(request: "Request") -> str:
        return "|".join([await resolve_key(f, request) for f in key_funcs])

    return key_func


async def resolve_key(key_func: KeyFunc, request: "Request") -> str:
    """Call ``key_func`` and await the result if it is async."""
    key = key_func(request)
    if inspect.isawaitable(key):
        return await key
    return key
