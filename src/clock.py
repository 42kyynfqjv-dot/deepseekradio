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


def air_now() -> datetime:
    """Wall time at which audio generated right now will actually air."""
    try:
        ahead = buffer.buffered_seconds()
    except Exception:
        ahead = 0.0
    return datetime.now() + timedelta(seconds=ahead)
