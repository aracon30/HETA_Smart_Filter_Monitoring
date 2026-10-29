"""
Login-Bremse – begrenzt Passwort-Rateversuche je Client-Adresse.

Die ersten FREE_ATTEMPTS Fehlversuche sind frei. Danach wird die Adresse
gesperrt; die Sperrdauer beginnt bei BASE_LOCK_SECONDS und verdoppelt sich mit
jedem weiteren Fehlversuch bis MAX_LOCK_SECONDS. Eine erfolgreiche Anmeldung
setzt den Zähler zurück; Einträge ohne Aktivität verfallen nach
FORGET_AFTER_SECONDS.
"""

import threading
import time
from collections.abc import Callable

FREE_ATTEMPTS = 5
BASE_LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 15 * 60
FORGET_AFTER_SECONDS = 60 * 60


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        # { client: (fehlversuche, gesperrt_bis, letzter_versuch) }
        self._entries: dict[str, tuple[int, float, float]] = {}

    def retry_after(self, client: str) -> int:
        """Verbleibende Sperrzeit in Sekunden (0 = Versuch erlaubt)."""
        now = self._clock()
        with self._lock:
            self._expire(now)
            entry = self._entries.get(client)
            if entry is None:
                return 0
            remaining = entry[1] - now
            return int(remaining) + 1 if remaining > 0 else 0

    def register_failure(self, client: str) -> int:
        """Zählt einen Fehlversuch und gibt die neue Sperrzeit in Sekunden zurück (0 = keine Sperre)."""
        now = self._clock()
        with self._lock:
            failures = self._entries.get(client, (0, 0.0, now))[0] + 1
            lock_seconds = 0
            if failures > FREE_ATTEMPTS:
                lock_seconds = min(MAX_LOCK_SECONDS, BASE_LOCK_SECONDS * 2 ** (failures - FREE_ATTEMPTS - 1))
            self._entries[client] = (failures, now + lock_seconds, now)
            return lock_seconds

    def register_success(self, client: str) -> None:
        with self._lock:
            self._entries.pop(client, None)

    def _expire(self, now: float) -> None:
        stale = [c for c, (_, until, last) in self._entries.items() if now - max(until, last) > FORGET_AFTER_SECONDS]
        for c in stale:
            del self._entries[c]
