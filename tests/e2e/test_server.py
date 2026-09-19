"""The example FastAPI app on a real uvicorn server, called over loopback with a real HTTP client.

Runs against every backend the ``live_server`` fixture provides: in-memory, fakeredis, and real Redis when
``RATE_LIMITER_REDIS_URL`` is set.
"""

import httpx

from tests.conftest import Clock
from tests.e2e.conftest import LiveServer

API_KEY = {"X-API-Key": "demo"}


def test_requests_within_the_limit_pass_with_rate_limit_headers(
    live_server: LiveServer, clock: Clock
) -> None:
    response = httpx.get(f"{live_server.url}/")

    assert response.status_code == 200
    assert response.json() == {"message": "hello"}
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert response.headers["X-RateLimit-Remaining"] == "9"


def test_global_limit_returns_real_429_then_recovers_after_refill(
    live_server: LiveServer, clock: Clock
) -> None:
    statuses = [httpx.get(f"{live_server.url}/").status_code for _ in range(10)]
    assert statuses == [200] * 10

    denied = httpx.get(f"{live_server.url}/")
    assert denied.status_code == 429
    assert denied.headers["X-RateLimit-Limit"] == "10"
    assert denied.headers["X-RateLimit-Remaining"] == "0"
    assert denied.headers["Retry-After"] == "1"  # one token at 5/s is 0.2s, rounded up

    clock.advance(1)  # refills 5 tokens

    assert [httpx.get(f"{live_server.url}/").status_code for _ in range(6)] == [200] * 5 + [429]


def test_api_key_limit_resets_with_the_window(live_server: LiveServer, clock: Clock) -> None:
    url = f"{live_server.url}/limited"
    assert [httpx.get(url, headers=API_KEY).status_code for _ in range(3)] == [200] * 3

    denied = httpx.get(url, headers=API_KEY)
    assert denied.status_code == 429
    assert denied.headers["X-RateLimit-Limit"] == "3"
    assert denied.headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(denied.headers["Retry-After"]) <= 10

    assert httpx.get(url, headers={"X-API-Key": "other"}).status_code == 200  # keys are independent

    clock.advance(10)

    assert httpx.get(url, headers=API_KEY).status_code == 200


def test_exempt_health_route_is_never_limited(live_server: LiveServer, clock: Clock) -> None:
    for _ in range(15):
        assert httpx.get(f"{live_server.url}/").status_code in (200, 429)

    assert httpx.get(f"{live_server.url}/health").status_code == 200
