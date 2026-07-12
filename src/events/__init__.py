"""Special-events engine (Track D): registry -> derivers -> overlay -> air.

``overlay`` is the design name the siblings import; the composition module's
file is ``compose.py`` — the alias below reconciles the two.
"""
from . import compose as overlay  # noqa: F401
from .compose import (ENGINE_NAMES, active_events, build_ctx,  # noqa: F401
                      daypart_matches_date, effective_schedule, engine_of,
                      same_air)
