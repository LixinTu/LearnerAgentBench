"""Virtual time. Every record timestamp and every event trigger uses this clock, never wall time."""
from __future__ import annotations

from datetime import datetime, timedelta


class VirtualClock:
    def __init__(self, now: datetime) -> None:
        self._now = now
        self.history: list[tuple[datetime, str]] = [(now, "init")]

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: int = 0, hours: int = 0, days: int = 0, reason: str = "") -> datetime:
        delta = timedelta(minutes=minutes, hours=hours, days=days)
        if delta < timedelta(0):
            raise ValueError("the clock only moves forward")
        self._now = self._now + delta
        self.history.append((self._now, reason or "advance"))
        return self._now

    def set(self, when: datetime, reason: str = "") -> datetime:
        if when < self._now:
            raise ValueError("the clock only moves forward")
        self._now = when
        self.history.append((self._now, reason or "set"))
        return self._now
