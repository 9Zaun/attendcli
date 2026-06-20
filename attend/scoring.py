"""Priority x urgency scoring (shared by ``attend tasks`` and ``attend crunch``).

Clarifications (authoritative over the PRD):
  p = priority (1-5; 5 = most important / most effort)
  d = days until due, clamped to a minimum (0.5) to avoid division blow-ups
  u = exp(D / d), capped so very small d doesn't explode
  score = p * u
Items without a due/event date use a large default d so they sort by priority.
"""

from __future__ import annotations

import math
from datetime import date

from . import config
from .dates import parse_iso, today

MIN_DAYS = 0.5


def reference_date(item: dict, items_by_id: dict[str, dict] | None = None) -> str | None:
    """Return the ISO date that drives an item's urgency.

    Deadlines use ``due``; events use ``event_time`` (date portion). A task that
    is *linked* to a deadline/event inherits that linked item's date — the link
    takes precedence over any optional ``due`` the task may also carry, so
    scoring and scheduling always track the real deadline/event. An unlinked
    task falls back to its own ``due``.
    """
    kind = item.get("kind")
    if kind == "deadline" and item.get("due"):
        return item["due"]
    if kind == "event" and item.get("event_time"):
        return item["event_time"][:10]
    if kind == "task":
        linked_id = item.get("linked_to")
        if linked_id and items_by_id and linked_id in items_by_id:
            linked_ref = reference_date(items_by_id[linked_id], items_by_id)
            if linked_ref:
                return linked_ref
        if item.get("due"):
            return item["due"]
    # Fallback for any kind that still carries a due
    if item.get("due"):
        return item["due"]
    return None


def days_until(ref_iso: str | None, ref_today: date | None = None) -> float | None:
    if not ref_iso:
        return None
    base = ref_today or today()
    return float((parse_iso(ref_iso) - base).days)


def score(
    item: dict,
    items_by_id: dict[str, dict] | None = None,
    ref_today: date | None = None,
) -> float:
    """Combined priority x urgency score (higher = more urgent/important)."""
    s = config.settings()
    decay = float(s["urgency_decay"])
    cap = float(s["urgency_cap"])
    no_due_default = float(s["no_due_default_days"])

    p = float(item.get("priority", s["priority_min"]))

    ref = reference_date(item, items_by_id)
    d = days_until(ref, ref_today)
    if d is None:
        d = no_due_default
    d = max(d, MIN_DAYS)

    u = math.exp(decay / d)
    u = min(u, cap)
    return p * u
