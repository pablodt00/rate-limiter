# Changelog

All notable changes are listed here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

## 0.1.0 - 2026-09-20

### Added
- Core algorithms (`TokenBucket`, `SlidingWindowCounter`, `FixedWindowCounter`), the `RateLimiter` facade and the
  in-memory and Redis backends.
- Client helpers (`rate_limited`, `async_rate_limited`, `RetryPolicy`, header parsing) and FastAPI integration
  (`rate_limit()` dependency, `RateLimitMiddleware`, key functions).
- Top-level re-exports and `rate_limiter.__version__`.
- `all` extra, CI workflow, and a PyPI publish workflow triggered by GitHub Releases.
