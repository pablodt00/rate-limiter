import dataclasses

import pytest

from rate_limiter.core import RateLimitResult


def make(**overrides: object) -> RateLimitResult:
    fields: dict[str, object] = {
        "allowed": True,
        "remaining": 4,
        "limit": 5,
        "reset_after": 1.5,
        "retry_after": None,
    }
    fields.update(overrides)
    return RateLimitResult(**fields)  # type: ignore[arg-type]


def test_is_frozen() -> None:
    result = make()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.allowed = False  # type: ignore[misc]


def test_compares_by_value() -> None:
    assert make() == make()
    assert make() != make(remaining=3)
