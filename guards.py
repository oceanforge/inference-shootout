"""Spend guards for the public demo instance.

Deliberately in-memory: no Redis, no database, no extra dependency for a demo
app. That means both guards are per-process and reset on redeploy, so a
DigitalOcean billing alert is the real backstop — see the spec. Self-hosters
running this on their own key disable both by setting their env vars to 0.
"""

import threading
from collections import defaultdict, deque


class RateLimiter:
    """Per-caller sliding window. `clock` returns monotonic seconds."""

    def __init__(self, per_minute: int, clock):
        self.per_minute = per_minute
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True


class DailyBudget:
    """Estimated spend against a ceiling, reset at UTC midnight.

    `clock` returns a timezone-aware UTC datetime.
    """

    def __init__(self, limit_usd: float, clock):
        self.limit_usd = limit_usd
        self._clock = clock
        self._day = None
        self._spent = 0.0
        self._lock = threading.Lock()

    def _roll_locked(self) -> None:
        today = self._clock().date()
        if self._day != today:
            self._day, self._spent = today, 0.0

    def remaining(self) -> float:
        if self.limit_usd <= 0:
            return float("inf")
        with self._lock:
            self._roll_locked()
            return max(0.0, self.limit_usd - self._spent)

    def allow(self) -> bool:
        return self.remaining() > 0

    def charge(self, usd: float) -> None:
        if self.limit_usd <= 0:
            return
        with self._lock:
            self._roll_locked()
            self._spent += usd
