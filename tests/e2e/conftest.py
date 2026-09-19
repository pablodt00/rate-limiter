import os
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

import fakeredis
import fakeredis.aioredis
import pytest
import redis
import redis.asyncio
import uvicorn
from fastapi import Request, Response

from examples.fastapi_app import create_app
from rate_limiter.backends import InMemoryBackend, RateLimiterBackend
from rate_limiter.backends.redis import RedisBackend


@dataclass
class LiveServer:
    url: str
    hits: list[str]  # path of every request that reached the server, allowed or not


def _make_backend(kind: str) -> tuple[RateLimiterBackend, Callable[[], None]]:
    """A backend of the given kind plus a cleanup function."""
    if kind == "memory":
        return InMemoryBackend(), lambda: None
    if kind == "fakeredis":
        fake_server = fakeredis.FakeServer()
        return (
            RedisBackend(
                fakeredis.FakeRedis(server=fake_server),
                fakeredis.aioredis.FakeRedis(server=fake_server),
            ),
            lambda: None,
        )
    url = os.environ.get("RATE_LIMITER_REDIS_URL")
    if url is None:
        pytest.skip("set RATE_LIMITER_REDIS_URL to run against a real Redis")
    sync_client = redis.Redis.from_url(url)
    sync_client.flushdb()
    backend = RedisBackend(sync_client, redis.asyncio.Redis.from_url(url))
    return backend, sync_client.flushdb


@pytest.fixture(
    params=[
        "memory",
        "fakeredis",
        pytest.param("real_redis", marks=pytest.mark.integration),
    ]
)
def live_server(request: pytest.FixtureRequest) -> Iterator[LiveServer]:
    """The example app on a real uvicorn server on a free loopback port, in a background thread."""
    backend, cleanup = _make_backend(request.param)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    app = create_app(backend)
    hits: list[str] = []

    @app.middleware("http")
    async def record_hits(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        hits.append(request.url.path)
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)

    yield LiveServer(url=f"http://127.0.0.1:{port}", hits=hits)

    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    cleanup()
