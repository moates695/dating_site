from app.ratelimit import RateLimiter


def test_allows_up_to_the_limit():
    limiter = RateLimiter(max_per_window=3, window_seconds=60)
    assert [limiter.allow("token", now=0.0) for _ in range(3)] == [True, True, True]


def test_blocks_beyond_the_limit():
    limiter = RateLimiter(max_per_window=2, window_seconds=60)
    limiter.allow("token", now=0.0)
    limiter.allow("token", now=1.0)
    assert limiter.allow("token", now=2.0) is False


def test_window_expires():
    limiter = RateLimiter(max_per_window=1, window_seconds=60)
    assert limiter.allow("token", now=0.0) is True
    assert limiter.allow("token", now=30.0) is False
    assert limiter.allow("token", now=61.0) is True


def test_tokens_are_limited_independently():
    limiter = RateLimiter(max_per_window=1, window_seconds=60)
    assert limiter.allow("one", now=0.0) is True
    assert limiter.allow("two", now=0.0) is True
    assert limiter.allow("one", now=0.0) is False


def test_blocked_attempts_do_not_extend_the_window():
    """A blocked attempt must not count as a hit, or a spammer keeps themselves out forever."""
    limiter = RateLimiter(max_per_window=1, window_seconds=60)
    limiter.allow("token", now=0.0)
    for moment in range(1, 60):
        limiter.allow("token", now=float(moment))
    assert limiter.allow("token", now=61.0) is True
