from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def next_occurrence(config: dict, after: datetime | None = None) -> datetime:
    """Return the next UTC instant. Repeated wall times run once; gaps move forward."""
    after = (after or datetime.now(UTC)).astimezone(UTC)
    zone = ZoneInfo(config["timezone"])
    first = after.astimezone(zone).date()
    candidates = []
    for day_offset in range(9):
        day = first + timedelta(days=day_offset)
        if config["frequency"] == "weekly" and day.weekday() != config["weekday"]:
            continue
        hours = range(24) if config["frequency"] == "hourly" else [config["hour"]]
        for hour in hours:
            naive = datetime(day.year, day.month, day.day, hour, config["minute"])
            # The first fold is the single occurrence of ambiguous local times.
            for _ in range(181):
                aware = naive.replace(tzinfo=zone, fold=0)
                instant = aware.astimezone(UTC)
                if instant.astimezone(zone).replace(tzinfo=None) == naive:
                    break
                naive += timedelta(minutes=1)
            if instant > after:
                candidates.append(instant)
    if not candidates:
        raise ValueError("Cannot calculate next schedule occurrence")
    return min(candidates)
