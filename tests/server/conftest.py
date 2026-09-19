import pytest


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Controls the time the RateLimiter facade sees, so windows can be crossed instantly."""
    clock = Clock()
    monkeypatch.setattr("rate_limiter.core.limiter.time.time", lambda: clock.now)
    return clock
