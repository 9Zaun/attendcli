"""Task/deadline/event store and query helpers.

Shared by the tasks commands (Phase 4), the dashboard's upcoming list (Phase 3),
and the crunch scheduler (Phase 6). Scoring lives in ``scoring.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import scoring, storage
from .dates import parse_iso, today

PENDING = "pending"
DONE = "done"
CANCELLED = "cancelled"

KINDS = {"task", "deadline", "event"}


def load() -> dict[str, Any]:
    return storage.load("tasks")


def save(data: dict[str, Any]) -> None:
    storage.save("tasks", data)


def items() -> list[dict[str, Any]]:
    return load().get("items", [])


def by_id_map(item_list: list[dict] | None = None) -> dict[str, dict]:
    return {i["id"]: i for i in (item_list if item_list is not None else items())}


def find(item_id: str) -> dict[str, Any] | None:
    target = str(item_id).lower()
    for i in items():
        if i["id"].lower() == target:
            return i
    return None


def next_id() -> str:
    data = load()
    n = data.get("next_id", 1)
    data["next_id"] = n + 1
    save(data)
    return f"t{n}"


def add(item: dict[str, Any]) -> None:
    data = load()
    data.setdefault("items", []).append(item)
    save(data)


def update(item_id: str, **fields: Any) -> bool:
    data = load()
    for i in data.get("items", []):
        if i["id"].lower() == str(item_id).lower():
            i.update(fields)
            save(data)
            return True
    return False


def pending(
    kind: str | None = None,
    subject: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    result = [i for i in items() if i.get("status") == PENDING]
    if kind:
        result = [i for i in result if i.get("kind") == kind]
    if subject:
        result = [i for i in result if (i.get("subject") or "").lower() == subject.lower()]
    if tag:
        result = [i for i in result if tag in (i.get("tags") or [])]
    return result


def sorted_by_score(
    item_list: list[dict] | None = None, ref_today: date | None = None
) -> list[dict[str, Any]]:
    """Return items sorted by priority x urgency score, descending."""
    pool = item_list if item_list is not None else pending()
    id_map = by_id_map()
    return sorted(
        pool,
        key=lambda i: scoring.score(i, id_map, ref_today),
        reverse=True,
    )


def is_fixed(item: dict) -> bool:
    """True when a task is pinned and must not be moved by the planner."""
    return bool(item.get("fixed"))


def pin_date(item: dict, id_map: dict[str, dict] | None = None) -> str | None:
    """Return the ISO date a fixed task is pinned to, or None.

    Uses the stored ``fixed_date`` when set; otherwise falls back to the task's
    reference date (linked deadline/event or own ``due``) for legacy rows that
    only have ``fixed=true``.
    """
    if not is_fixed(item):
        return None
    if item.get("fixed_date"):
        return item["fixed_date"]
    ref = scoring.reference_date(item, id_map or by_id_map())
    return ref[:10] if ref else None


def upcoming(days: int = 7, ref_today: date | None = None) -> list[dict[str, Any]]:
    """Pending items whose reference date falls within the next ``days`` days."""
    base = ref_today or today()
    id_map = by_id_map()
    result = []
    for i in pending():
        ref = scoring.reference_date(i, id_map)
        if not ref:
            continue
        delta = (parse_iso(ref[:10]) - base).days
        if 0 <= delta <= days:
            result.append(i)
    return sorted_by_score(result, ref_today)
