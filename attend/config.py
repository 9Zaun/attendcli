"""Configuration access helpers.

The config store holds the semester definition, the fixed time structure,
subjects, and global settings. This module centralizes reads/writes and the
default settings so the rest of the app never hard-codes them.
"""

from __future__ import annotations

from typing import Any

from . import storage

# Global tunables. Clarifications override the PRD here:
#  - priority scale is 1-5 (no separate effort field)
#  - urgency u = exp(D/d) with d clamped and u capped
DEFAULT_SETTINGS: dict[str, Any] = {
    "rest_message": "Rest day. No classes scheduled. Recover and reset.",
    "editor": "",  # falls back to $EDITOR / $VISUAL / vi at use time
    # Priority x urgency scoring
    "urgency_decay": 7.0,        # D in u = exp(D/d)
    "urgency_cap": 100.0,        # cap on u so tiny d doesn't blow up
    "no_due_default_days": 30,   # d for items without a due/event date
    "priority_min": 1,
    "priority_max": 5,
    # Crunch scheduler
    "crunch_capacity_mode": "priority_sum",  # or "task_count"
    "crunch_daily_capacity": 8,              # max sum of priorities (or task count) per day
    "crunch_skip_weekends": False,           # if True, don't schedule Sat/Sun
    "crunch_horizon_days": 60,               # how far ahead to plan for no-due tasks
}


def load() -> dict[str, Any]:
    return storage.load("config")


def save(cfg: dict[str, Any]) -> None:
    storage.save("config", cfg)


def settings() -> dict[str, Any]:
    """Return settings merged over defaults (defaults fill any missing keys)."""
    cfg = load()
    merged = dict(DEFAULT_SETTINGS)
    merged.update(cfg.get("settings", {}))
    return merged


def get_setting(key: str) -> Any:
    return settings().get(key, DEFAULT_SETTINGS.get(key))


def subjects() -> list[dict[str, Any]]:
    return load().get("subjects", [])


def subject_codes() -> list[str]:
    return [s["code"] for s in subjects()]


def find_subject(identifier: str) -> dict[str, Any] | None:
    """Case-insensitive subject lookup by full code OR short alias."""
    if not identifier:
        return None
    target = identifier.strip().lower()
    for s in subjects():
        if s["code"].lower() == target or (s.get("alias", "").lower() == target):
            return s
    return None


def resolve_code(identifier: str) -> str | None:
    """Return the canonical code for a code/alias, or None if unknown."""
    s = find_subject(identifier)
    return s["code"] if s else None


def alias_for(code: str) -> str:
    """Short alias for a subject code (falls back to the code itself)."""
    s = find_subject(code)
    if not s:
        return code
    return s.get("alias") or s["code"]


def display_label(code: str) -> str:
    """'ALIAS (CODE)' label; just the code if alias == code or missing."""
    s = find_subject(code)
    if not s:
        return code
    alias = s.get("alias") or s["code"]
    if alias.lower() == s["code"].lower():
        return s["code"]
    return f"{alias} ({s['code']})"


def reserve_for(code: str) -> int:
    s = find_subject(code)
    return int(s.get("reserve", 0)) if s else 0


def time_structure() -> list[dict[str, Any]]:
    return load().get("time_structure", [])


def semester() -> dict[str, Any]:
    return load().get("semester", {})
