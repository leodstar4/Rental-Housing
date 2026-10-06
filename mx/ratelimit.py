"""In-memory token buckets per client IP (10 POST/min, 120 GET/min by default)."""

from __future__ import annotations

import math
import threading
import time
from typing import Callable


class TokenBucket:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> float | None:
        """Consume one token; return None if allowed, else seconds to wait."""
        now = self.clock()
        with self._lock:
            tokens, last = self._state.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if len(self._state) >= 10_000 and key not in self._state:  # bound memory before growth
                for k in sorted(self._state, key=lambda k: self._state[k][1])[:5_000]:
                    del self._state[k]
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                return None
            self._state[key] = (tokens, now)
            return (1 - tokens) / self.rate


class RateLimiter:
    def __init__(self, post_per_minute: int = 10, get_per_minute: int = 120,
                 clock: Callable[[], float] = time.monotonic):
        self.post = TokenBucket(post_per_minute, clock)
        self.get = TokenBucket(get_per_minute, clock)

    def check(self, ip: str, method: str) -> int | None:
        """None if allowed, else Retry-After in whole seconds."""
        wait = (self.post if method == "POST" else self.get).take(ip)
        return None if wait is None else max(1, math.ceil(wait))
