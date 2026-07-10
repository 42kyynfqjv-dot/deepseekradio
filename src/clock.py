"""The station clock: what time it is ON AIR, not on the wall.

The generator runs up to buffer_target minutes ahead of playback, so audio
written "now" airs buffered_seconds later. Every schedule decision (which
show to write for, when to hand off, what day it is) and every spoken sense
of time must use AIR time — wall time is only correct for real elapsed-time
concerns (cooldowns, retries, tail freshness).

With an empty buffer air time equals wall time, so cold starts behave.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import buffer


# The buffer under-counts the real air delay: the player inserts ad breaks
# and boundary bumpers that are not queued audio (~90-120s per hour of air).
# Correct for it so spoken time checks land inside their hedge. The wall
# clock itself is NTP-disciplined (chained to the same atomic reference NIST
# serves) — air offset, not clock source, is the accuracy problem.
_BREAK_OVERHEAD = 1.04


def air_now() -> datetime:
    """Wall time at which audio generated right now will actually air."""
    try:
        ahead = buffer.buffered_seconds() * _BREAK_OVERHEAD
    except Exception:
        ahead = 0.0
    return datetime.now() + timedelta(seconds=ahead)


def spoken_air_time(now: datetime | None = None) -> str:
    """The air clock rounded to 5 minutes, said like a person: 'about 8:25 PM'
    is honest; '8:23 PM' would be a lie half the time. Callers say the 'about'.
    Pass `now` when you already hold air_now() — buffered_seconds globs the
    queue directory, and twice per line adds up."""
    t = now or air_now()
    t = (t.replace(minute=0, second=0, microsecond=0)
         + timedelta(minutes=round(t.minute / 5) * 5))
    h12 = t.hour % 12 or 12
    if t.minute == 0:
        return f"{h12} o'clock"
    return f"{h12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
