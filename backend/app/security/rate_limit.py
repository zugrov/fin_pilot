import threading
import time

from app.config import Settings
from app.errors import AppError


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        current = time.monotonic()
        with self._lock:
            fresh = [item for item in self._hits.get(key, []) if current - item < window_seconds]
            if len(fresh) >= limit:
                self._hits[key] = fresh
                return False
            fresh.append(current)
            self._hits[key] = fresh
            return True


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url)

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count) <= limit


def build_rate_limiter(settings: Settings) -> MemoryRateLimiter | RedisRateLimiter:
    if settings.rate_limit_backend == "redis":
        return RedisRateLimiter(settings.redis_url)
    return MemoryRateLimiter()


def enforce(
    limiter: MemoryRateLimiter | RedisRateLimiter, key: str, limit: int, window: int
) -> None:
    if not limiter.allow(key, limit, window):
        raise AppError(429, "rate_limited", "Слишком много попыток, попробуйте позже")
