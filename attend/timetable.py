"""Timetable versioning and per-day slot resolution.

A timetable is a list of versions, each with an ``effective_from`` date and a
``days`` map (Mon..Sat -> ordered slot list). Date-based queries pick the latest
version whose ``effective_from`` is <= the query date, so historical logs are
reconstructed against the timetable that was in force at the time.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import storage
from .dates import parse_iso, weekday_short

# Slot types
SUBJECT = "subject"
TUTORIAL = "tutorial-slot"
BREAK = "break"
LUNCH = "lunch"

NON_LOGGABLE = {BREAK, LUNCH}


def load() -> dict[str, Any]:
    return storage.load("timetable")


def save(data: dict[str, Any]) -> None:
    storage.save("timetable", data)


def version_for(query: date) -> dict[str, Any] | None:
    """Return the timetable version effective on ``query`` (latest <= query)."""
    versions = load().get("versions", [])
    chosen = None
    chosen_date = None
    for v in versions:
        eff = parse_iso(v["effective_from"])
        if eff <= query and (chosen_date is None or eff > chosen_date):
            chosen = v
            chosen_date = eff
    # If nothing is effective yet (query before first version), fall back to the
    # earliest version so the day view still shows a schedule.
    if chosen is None and versions:
        chosen = min(versions, key=lambda v: parse_iso(v["effective_from"]))
    return chosen


def add_version(days: dict[str, list[dict]], effective_from: str) -> None:
    data = load()
    data.setdefault("versions", []).append(
        {"effective_from": effective_from, "days": days}
    )
    save(data)


def slots_for_weekday(version: dict[str, Any], weekday: str) -> list[dict]:
    """Return the ordered slot list for a weekday short name (Mon..Sat)."""
    if not version:
        return []
    return version.get("days", {}).get(weekday, [])


def slots_for_date(query: date, *, weekday_override: str | None = None) -> list[dict]:
    """Resolve the slot list for a date.

    ``weekday_override`` lets a working Saturday borrow another day's timetable.
    """
    version = version_for(query)
    wd = weekday_override or weekday_short(query)
    return slots_for_weekday(version, wd)


def is_loggable(slot: dict) -> bool:
    return slot.get("type") not in NON_LOGGABLE
