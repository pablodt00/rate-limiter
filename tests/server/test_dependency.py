from conftest import Clock
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rate_limiter.backends import InMemoryBackend
from rate_limiter.core import FixedWindowCounter
from rate_limiter.core.limiter import RateLimiter
from rate_limiter.server.fastapi_dependency import rate_limit
from rate_limiter.server.keys import by_header


def make_app(limit: int = 2, **kwargs: object) -> TestClient:
    limiter = RateLimiter(FixedWindowCounter(limit=limit, window_seconds=10), InMemoryBackend())
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(rate_limit(limiter, **kwargs))])  # type: ignore[arg-type]
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/free")
    def free() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def test_allowed_requests_carry_rate_limit_headers(clock: Clock) -> None:
    response = make_app(limit=2).get("/ping")
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert int(response.headers["X-RateLimit-Reset"]) > 0


def test_over_the_limit_gives_429_with_retry_headers(clock: Clock) -> None:
    client = make_app(limit=2)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    denied = client.get("/ping")
    assert denied.status_code == 429
    assert denied.json() == {"detail": "Rate limit exceeded"}
    assert denied.headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(denied.headers["Retry-After"]) <= 10


def test_requests_succeed_again_after_the_window(clock: Clock) -> None:
    client = make_app(limit=1)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429
    clock.advance(10)
    assert client.get("/ping").status_code == 200


def test_routes_without_the_dependency_are_not_limited(clock: Clock) -> None:
    client = make_app(limit=1)
    for _ in range(5):
        assert client.get("/free").status_code == 200
        assert "X-RateLimit-Limit" not in client.get("/free").headers


def test_callers_are_limited_independently(clock: Clock) -> None:
    client = make_app(limit=1, key_func=by_header("X-API-Key"))
    assert client.get("/ping", headers={"X-API-Key": "a"}).status_code == 200
    assert client.get("/ping", headers={"X-API-Key": "a"}).status_code == 429
    assert client.get("/ping", headers={"X-API-Key": "b"}).status_code == 200


def test_cost_is_charged_per_request(clock: Clock) -> None:
    client = make_app(limit=4, cost=2)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429


def test_cost_above_the_limit_is_denied_without_retry_after(clock: Clock) -> None:
    denied = make_app(limit=1, cost=5).get("/ping")
    assert denied.status_code == 429
    assert "Retry-After" not in denied.headers
