from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from rate_limiter.backends import InMemoryBackend
from rate_limiter.core import FixedWindowCounter
from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server.fastapi_dependency import rate_limit
from rate_limiter.server.fastapi_middleware import RateLimitMiddleware
from rate_limiter.server.keys import by_header
from tests.conftest import Clock


def make_limiter(limit: int) -> RateLimiter:
    return RateLimiter(FixedWindowCounter(limit=limit, window_seconds=10), InMemoryBackend())


def make_app(limit: int = 2, **kwargs: object) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=make_limiter(limit), **kwargs)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter([b"a", b"b", b"c"]))

    return app


def test_allowed_requests_carry_rate_limit_headers(clock: Clock) -> None:
    response = TestClient(make_app(limit=2)).get("/ping")
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in response.headers


def test_over_the_limit_gives_json_429_and_skips_the_app(clock: Clock) -> None:
    client = TestClient(make_app(limit=1))
    assert client.get("/ping").status_code == 200
    denied = client.get("/ping")
    assert denied.status_code == 429
    assert denied.json() == {"detail": "Rate limit exceeded"}
    assert denied.headers["content-type"] == "application/json"
    assert denied.headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(denied.headers["Retry-After"]) <= 10


def test_requests_succeed_again_after_the_window(clock: Clock) -> None:
    client = TestClient(make_app(limit=1))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429
    clock.advance(10)
    assert client.get("/ping").status_code == 200


def test_exempt_paths_are_not_counted_or_decorated(clock: Clock) -> None:
    client = TestClient(make_app(limit=1, exempt_paths=["/health"]))
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers
    assert client.get("/ping").status_code == 200


def test_streaming_responses_still_stream_with_headers(clock: Clock) -> None:
    response = TestClient(make_app(limit=5)).get("/stream")
    assert response.content == b"abc"
    assert response.headers["X-RateLimit-Limit"] == "5"


def test_custom_key_func_and_cost(clock: Clock) -> None:
    client = TestClient(make_app(limit=2, key_func=by_header("X-API-Key"), cost=2))
    assert client.get("/ping", headers={"X-API-Key": "a"}).status_code == 200
    assert client.get("/ping", headers={"X-API-Key": "a"}).status_code == 429
    assert client.get("/ping", headers={"X-API-Key": "b"}).status_code == 200


def test_coexists_with_the_dependency_and_keeps_its_headers(clock: Clock) -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=make_limiter(10))
    strict = make_limiter(1)

    @app.get("/strict", dependencies=[Depends(rate_limit(strict))])
    def strict_route() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/open")
    def open_route() -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(app)
    first = client.get("/strict")
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"  # the route's own, stricter limit wins
    assert client.get("/strict").status_code == 429
    assert client.get("/open").headers["X-RateLimit-Limit"] == "10"


def test_middleware_limit_applies_across_routes(clock: Clock) -> None:
    client = TestClient(make_app(limit=2))
    assert client.get("/ping").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/ping").status_code == 429
