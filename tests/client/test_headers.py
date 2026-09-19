import pytest

from rate_limiter.client.headers import (
    ParsedRateLimitInfo,
    parse_rate_limit_headers,
    parse_retry_after,
    register_header_aliases,
)


def test_retry_after_delta_seconds() -> None:
    assert parse_retry_after({"Retry-After": "120"}) == 120
    assert parse_retry_after({"Retry-After": " 1.5 "}) == 1.5


def test_retry_after_http_date() -> None:
    # 1994-11-06 08:49:37 GMT is epoch 784111777.
    headers = {"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}
    assert parse_retry_after(headers, now=784111777 - 30) == pytest.approx(30)


def test_retry_after_date_in_the_past_is_zero() -> None:
    headers = {"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}
    assert parse_retry_after(headers, now=784111777 + 100) == 0


def test_retry_after_negative_is_clamped() -> None:
    assert parse_retry_after({"Retry-After": "-5"}) == 0


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "soon"}, {"Retry-After": ""}])
def test_retry_after_missing_or_garbage(headers: dict[str, str]) -> None:
    assert parse_retry_after(headers) is None


def test_header_names_are_case_insensitive() -> None:
    assert parse_retry_after({"rEtRy-AfTeR": "3"}) == 3


def test_standard_x_ratelimit_headers() -> None:
    info = parse_rate_limit_headers(
        {"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "7", "X-RateLimit-Reset": "42"}
    )
    assert info == ParsedRateLimitInfo(limit=100, remaining=7, reset_after=42, retry_after=None)


def test_ietf_draft_header_names() -> None:
    info = parse_rate_limit_headers({"RateLimit-Limit": "10", "RateLimit-Remaining": "0"})
    assert (info.limit, info.remaining) == (10, 0)


def test_openai_style_headers_with_duration_reset() -> None:
    info = parse_rate_limit_headers(
        {
            "x-ratelimit-limit-requests": "60",
            "x-ratelimit-remaining-requests": "59",
            "x-ratelimit-reset-requests": "1m30s",
        }
    )
    assert (info.limit, info.remaining, info.reset_after) == (60, 59, 90)


def test_millisecond_duration() -> None:
    info = parse_rate_limit_headers({"x-ratelimit-reset-requests": "250ms"})
    assert info.reset_after == pytest.approx(0.25)


def test_epoch_reset_becomes_seconds_from_now() -> None:
    info = parse_rate_limit_headers({"X-RateLimit-Reset": "1700000060"}, now=1700000000)
    assert info.reset_after == pytest.approx(60)


def test_retry_after_is_included() -> None:
    assert parse_rate_limit_headers({"Retry-After": "9"}).retry_after == 9


def test_unparseable_values_become_none() -> None:
    info = parse_rate_limit_headers(
        {"X-RateLimit-Limit": "lots", "X-RateLimit-Remaining": "", "X-RateLimit-Reset": "later"}
    )
    assert info == ParsedRateLimitInfo()


def test_no_headers_gives_empty_info() -> None:
    assert parse_rate_limit_headers({}) == ParsedRateLimitInfo()


def test_registered_alias_is_recognised() -> None:
    register_header_aliases("remaining", "x-acme-quota-left")
    assert parse_rate_limit_headers({"X-Acme-Quota-Left": "4"}).remaining == 4


def test_registering_alias_for_unknown_field_fails() -> None:
    with pytest.raises(ValueError):
        register_header_aliases("nope", "x-whatever")
