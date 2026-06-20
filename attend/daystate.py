"""Per-day operational state (working-Saturday decisions, holiday flags).

This is separate from attendance events: it records *how* a day should be
treated (which timetable a working Saturday follows, whether a day is a holiday)
so re-running ``attend day``/``attend log`` doesn't re-ask.
"""

from __future__ import annotations

from typing import Any

from . import storage


def load() -> dict[str, Any]:
    return storage.load("daystate")


def save(data: dict[str, Any]) -> None:
    storage.save("daystate", data)


def get(d: str) -> dict[str, Any]:
    return load().get("days", {}).get(d, {})


def set_state(d: str, **fields: Any) -> None:
    data = load()
    days = data.setdefault("days", {})
    entry = days.setdefault(d, {})
    entry.update(fields)
    save(data)


def saturday_decision(d: str) -> dict[str, Any] | None:
    """Return a stored working-Saturday decision for a date, if any.

    Shape: {"working": bool, "follows": "Mon"} when working, or
    {"working": False} when declared non-working.
    """
    st = get(d)
    if "sat_working" in st:
        return {"working": st["sat_working"], "follows": st.get("sat_follows")}
    return None


def record_saturday(d: str, working: bool, follows: str | None = None) -> None:
    set_state(d, sat_working=working, sat_follows=follows)


def mark_holiday(d: str) -> None:
    set_state(d, holiday=True)


def is_holiday(d: str) -> bool:
    return bool(get(d).get("holiday"))
