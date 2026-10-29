"""Tests für die Login-Bremse (login_guard.py)."""

from login_guard import BASE_LOCK_SECONDS, FORGET_AFTER_SECONDS, FREE_ATTEMPTS, MAX_LOCK_SECONDS, LoginThrottle


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _throttle():
    clock = FakeClock()
    return LoginThrottle(clock=clock), clock


def test_free_attempts_do_not_lock():
    t, _ = _throttle()
    for _ in range(FREE_ATTEMPTS):
        assert t.register_failure("a") == 0
    assert t.retry_after("a") == 0


def test_lock_starts_after_free_attempts_and_doubles():
    t, _ = _throttle()
    for _ in range(FREE_ATTEMPTS):
        t.register_failure("a")
    assert t.register_failure("a") == BASE_LOCK_SECONDS
    assert t.retry_after("a") > 0
    assert t.register_failure("a") == 2 * BASE_LOCK_SECONDS


def test_lock_is_capped():
    t, _ = _throttle()
    for _ in range(FREE_ATTEMPTS + 30):
        lock = t.register_failure("a")
    assert lock == MAX_LOCK_SECONDS


def test_lock_expires_with_time():
    t, clock = _throttle()
    for _ in range(FREE_ATTEMPTS + 1):
        t.register_failure("a")
    clock.now += BASE_LOCK_SECONDS + 1
    assert t.retry_after("a") == 0


def test_success_resets_counter():
    t, _ = _throttle()
    for _ in range(FREE_ATTEMPTS):
        t.register_failure("a")
    t.register_success("a")
    assert t.register_failure("a") == 0


def test_clients_are_independent():
    t, _ = _throttle()
    for _ in range(FREE_ATTEMPTS + 1):
        t.register_failure("a")
    assert t.retry_after("a") > 0
    assert t.retry_after("b") == 0


def test_stale_entries_are_forgotten():
    t, clock = _throttle()
    for _ in range(FREE_ATTEMPTS):
        t.register_failure("a")
    clock.now += FORGET_AFTER_SECONDS + 1
    t.retry_after("a")  # löst Aufräumen aus
    assert t.register_failure("a") == 0
