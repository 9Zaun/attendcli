"""Week box generation and access.

Week boxes are derived from the semester start/end dates. Regeneration after a
semester end-date change preserves any goal/reflection text already entered.
"""

from __future__ import annotations

from typing import Any

from . import config, storage
from .dates import parse_iso, to_iso, total_weeks, week_start_date


def load() -> dict[str, Any]:
    return storage.load("weeks")


def save(data: dict[str, Any]) -> None:
    storage.save("weeks", data)


def regenerate() -> None:
    """(Re)build week boxes from the semester dates, preserving existing text."""
    sem = config.semester()
    if not sem:
        return
    start = parse_iso(sem["start"])
    end = parse_iso(sem["end"])
    n = total_weeks(start, end)

    existing = {w["week_number"]: w for w in load().get("weeks", [])}
    weeks: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        prev = existing.get(i, {})
        weeks.append(
            {
                "week_number": i,
                "start_date": to_iso(week_start_date(i, start)),
                "goal": prev.get("goal", ""),
                "reflection": prev.get("reflection", ""),
            }
        )
    save({"weeks": weeks})


def all_weeks() -> list[dict[str, Any]]:
    return load().get("weeks", [])


def get_week(n: int) -> dict[str, Any] | None:
    for w in all_weeks():
        if w["week_number"] == n:
            return w
    return None
