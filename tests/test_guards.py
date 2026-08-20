from datetime import datetime, timedelta, timezone
from guards import RateLimiter, DailyBudget


class FakeClock:
    """Injected so budget-reset behaviour is tested without sleeping."""

    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, delta):
        self.value += delta


def test_rate_limiter_allows_up_to_the_limit_then_refuses():
    clock = FakeClock(1000.0)
    limiter = RateLimiter(per_minute=3, clock=clock)
    assert [limiter.allow("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_window_frees_up():
    clock = FakeClock(1000.0)
    limiter = RateLimiter(per_minute=1, clock=clock)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False
    clock.advance(61)
    assert limiter.allow("1.2.3.4") is True


def test_rate_limiter_tracks_callers_separately():
    limiter = RateLimiter(per_minute=1, clock=FakeClock(1000.0))
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("5.6.7.8") is True


def test_rate_limiter_disabled_by_zero():
    limiter = RateLimiter(per_minute=0, clock=FakeClock(1000.0))
    assert all(limiter.allow("1.2.3.4") for _ in range(100))


def test_budget_refuses_once_the_ceiling_is_reached():
    budget = DailyBudget(limit_usd=1.00, clock=FakeClock(datetime(2026, 8, 20, 12, tzinfo=timezone.utc)))
    assert budget.allow() is True
    budget.charge(0.99)
    assert budget.allow() is True
    budget.charge(0.02)
    assert budget.allow() is False


def test_budget_resets_at_utc_midnight():
    clock = FakeClock(datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc))
    budget = DailyBudget(limit_usd=1.00, clock=clock)
    budget.charge(5.00)
    assert budget.allow() is False
    clock.advance(timedelta(minutes=2))
    assert budget.allow() is True
    assert budget.remaining() == 1.00


def test_budget_disabled_by_zero():
    budget = DailyBudget(limit_usd=0, clock=FakeClock(datetime(2026, 8, 20, tzinfo=timezone.utc)))
    budget.charge(1_000_000)
    assert budget.allow() is True
