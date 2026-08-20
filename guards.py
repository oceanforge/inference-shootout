"""Spend guards for the public demo instance.

Deliberately in-memory: no Redis, no database, no extra dependency for a demo
app. That means both guards are per-process and reset on redeploy, so a
DigitalOcean billing alert is the real backstop — see the spec. Self-hosters
running this on their own key disable both by setting their env vars to 0.
"""

import threading
from collections import deque


class RateLimiter:
    """Per-caller sliding window. `clock` returns monotonic seconds."""

    def __init__(self, per_minute: int, clock):
        self.per_minute = per_minute
        self._clock = clock
        self._hits: dict[str, deque] = {}
        self._swept = 0.0
        self._lock = threading.Lock()

    def _sweep_locked(self, now: float) -> None:
        """Forget callers whose window has emptied.

        Without this, `_hits` keeps one entry per IP that ever touched a public
        endpoint, forever. Swept at most once a minute so a busy instance does
        not pay for the walk on every request.
        """
        if now - self._swept < 60:
            return
        self._swept = now
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= 60]:
            del self._hits[key]

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            hits = self._hits.setdefault(key, deque())
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
