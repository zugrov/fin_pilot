import pytest
from app.security.rate_limit import RedisRateLimiter


class _Boom:
    def pipeline(self) -> None:
        raise ConnectionError("redis down")


def _limiter(fail_closed: bool) -> RedisRateLimiter:
    limiter = RedisRateLimiter.__new__(RedisRateLimiter)
    limiter._redis = _Boom()
    limiter._fail_closed = fail_closed
    return limiter


def test_production_redis_outage_denies() -> None:
    assert _limiter(True).allow("login", 5, 60) is False


def test_non_production_redis_outage_raises() -> None:
    with pytest.raises(ConnectionError):
        _limiter(False).allow("login", 5, 60)
