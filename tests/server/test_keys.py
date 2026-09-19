import pytest
from starlette.requests import Request

from rate_limiter.server.keys import by_header, by_ip, by_route, combine, resolve_key


def make_request(
    path: str = "/items/1",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    client: tuple[str, int] | None = ("1.2.3.4", 5000),
    route_path: str | None = None,
) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    if route_path is not None:
        scope["route"] = type("Route", (), {"path": route_path})()
    return Request(scope)


def test_by_ip() -> None:
    assert by_ip(make_request()) == "1.2.3.4"


def test_by_ip_without_client() -> None:
    assert by_ip(make_request(client=None)) == "unknown"


def test_by_header_uses_the_value() -> None:
    key_func = by_header("X-API-Key")
    assert key_func(make_request(headers={"x-api-key": "abc"})) == "x-api-key:abc"
    assert key_func(make_request(headers={"x-api-key": "abc"})) != key_func(
        make_request(headers={"x-api-key": "def"})
    )


def test_by_header_missing_header_shares_a_bucket() -> None:
    key_func = by_header("X-API-Key")
    assert key_func(make_request()) == key_func(make_request(client=("9.9.9.9", 1)))


def test_by_route_uses_path_when_routing_has_not_run() -> None:
    assert by_route(make_request(path="/items/1")) == "GET:/items/1"


def test_by_route_prefers_the_route_template() -> None:
    request = make_request(path="/items/1", route_path="/items/{id}")
    assert by_route(request) == "GET:/items/{id}"


@pytest.mark.asyncio
async def test_combine_joins_sync_and_async_key_funcs() -> None:
    async def by_tenant(request: Request) -> str:
        return "tenant-7"

    key_func = combine(by_ip, by_tenant, by_route)
    assert await resolve_key(key_func, make_request()) == "1.2.3.4|tenant-7|GET:/items/1"


def test_combine_needs_a_key_func() -> None:
    with pytest.raises(ValueError):
        combine()


@pytest.mark.asyncio
async def test_resolve_key_handles_plain_custom_functions() -> None:
    assert await resolve_key(lambda request: "custom", make_request()) == "custom"
