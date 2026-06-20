"""Attendance event store and bunk-economy engine.

The engine is intentionally independent of the timetable: it consumes
``(date, subject, status)`` events regardless of how they were produced (normal
slot, swapped slot, resolved tutorial). All bunk math is derived directly from
the 75% rule via the slack model.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from . import config, daystate, storage, timetable
from .dates import parse_iso, to_iso, weekday_short

# Status codes
PRESENT = "Y"
ABSENT = "N"
CANCELLED = "C"


def load() -> dict[str, Any]:
    return storage.load("attendance")


def save(data: dict[str, Any]) -> None:
    storage.save("attendance", data)


def events() -> list[dict[str, Any]]:
    return load().get("events", [])


def append_events(new_events: list[dict[str, Any]]) -> None:
    data = load()
    data.setdefault("events", []).extend(new_events)
    save(data)


def replace_events_for_date(d: str, new_events: list[dict[str, Any]]) -> None:
    """Remove any existing events for a date, then add the provided ones.

    Used when re-logging a day or declaring a holiday so a day is never
    double-counted.
    """
    data = load()
    kept = [e for e in data.get("events", []) if e.get("date") != d]
    kept.extend(new_events)
    data["events"] = kept
    save(data)


def has_events_for_date(d: str) -> bool:
    return any(e.get("date") == d for e in events())


# --------------------------------------------------------------------------- #
# Bunk economy
# --------------------------------------------------------------------------- #


def counts_from(event_list: list[dict[str, Any]], code: str) -> dict[str, int]:
    """Return P/A/C counts for a subject across the supplied events."""
    p = a = c = 0
    target = code.lower()
    for e in event_list:
        subj = e.get("subject")
        if not subj or subj.lower() != target:
            continue
        st = e.get("status")
        if st == PRESENT:
            p += 1
        elif st == ABSENT:
            a += 1
        elif st == CANCELLED:
            c += 1
    return {"P": p, "A": a, "C": c}


def counts_for(code: str) -> dict[str, int]:
    """Return P/A/C counts for a subject across all logged events."""
    p = a = c = 0
    target = code.lower()
    for e in events():
        subj = e.get("subject")
        if not subj or subj.lower() != target:
            continue
        st = e.get("status")
        if st == PRESENT:
            p += 1
        elif st == ABSENT:
            a += 1
        elif st == CANCELLED:
            c += 1
    return {"P": p, "A": a, "C": c}


def slack_from(p: int, a: int) -> int:
    return p - 3 * a


def safe_bunks_from(slack: int) -> int:
    return max(0, slack // 3)


def remaining_classes(code: str, ref_today: date | None = None) -> int:
    """Upper-bound count of scheduled slots for a subject until semester end.

    Walks the effective timetable day-by-day from tomorrow to the *tentative*
    semester end, counting weekday slots scheduled for the subject (Saturdays and
    Sundays are excluded since working-Saturday timetables aren't known ahead).

    Already-declared holidays are subtracted (they're known no-class days). The
    result is still an **upper bound**, not a guarantee: future holidays, exam
    blocks, swaps and cancellations aren't all known in advance and can only make
    the real number smaller.
    """
    sem = config.semester()
    if not sem:
        return 0
    base = ref_today or date.today()
    end = parse_iso(sem["end"])
    target = code.lower()

    # Pull the known holiday dates once so we don't reload the store per day.
    holidays = {
        d for d, st in daystate.load().get("days", {}).items()
        if st.get("holiday")
    }

    count = 0
    from datetime import timedelta

    cur = base + timedelta(days=1)
    while cur <= end:
        wd = weekday_short(cur)
        if wd not in ("Sat", "Sun") and to_iso(cur) not in holidays:
            for slot in timetable.slots_for_date(cur):
                if slot.get("type") == timetable.SUBJECT and \
                        str(slot.get("subject", "")).lower() == target:
                    count += 1
        cur += timedelta(days=1)
    return count


def recovery_attends(slack: int) -> int:
    """Minimum consecutive presents needed to reach non-negative slack.

    Each present adds 1 to slack, so to climb from a negative slack ``s`` back to
    0 requires ``-s`` consecutive presents.
    """
    return max(0, -slack)


def split_buckets(safe: int, reserve_target: int) -> dict[str, int]:
    """Split earned safe bunks into reserve-first, then spendable.

    Reserve is *earned*, not pre-allocated: the first ``reserve_target`` earned
    bunks fill the reserve bucket, anything beyond is spendable. ``reserve_unearned``
    is how much of the reserve target hasn't been earned yet.
    """
    reserve_earned = min(safe, reserve_target)
    spendable = max(0, safe - reserve_target)
    reserve_unearned = max(0, reserve_target - reserve_earned)
    return {
        "spendable_bunks": spendable,
        "reserve_earned": reserve_earned,
        "reserve_target": reserve_target,
        "reserve_unearned": reserve_unearned,
    }


def economy_for(code: str, ref_today: date | None = None) -> dict[str, Any]:
    """Full bunk-economy snapshot for one subject."""
    counts = counts_for(code)
    p, a, c = counts["P"], counts["A"], counts["C"]
    slack = slack_from(p, a)
    safe = safe_bunks_from(slack)
    reserve = config.reserve_for(code)
    buckets = split_buckets(safe, reserve)

    need = recovery_attends(slack)
    remaining = remaining_classes(code, ref_today)
    recoverable = need <= remaining if need > 0 else True

    return {
        "code": code,
        "alias": config.alias_for(code),
        "P": p,
        "A": a,
        "C": c,
        "slack": slack,
        "safe_bunks": safe,
        "reserve": reserve,
        "below_75": slack < 0,
        "at_floor": slack == 0,
        "recovery_attends": need,
        "remaining_classes": remaining,
        "recoverable": recoverable,
        **buckets,
    }


def economy_from(event_list: list[dict[str, Any]], code: str) -> dict[str, Any]:
    """Economy snapshot for a subject computed from an explicit event list.

    Used by the logging summary to show before/after deltas without mutating the
    on-disk store mid-flow.
    """
    counts = counts_from(event_list, code)
    p, a = counts["P"], counts["A"]
    slack = slack_from(p, a)
    safe = safe_bunks_from(slack)
    reserve = config.reserve_for(code)
    buckets = split_buckets(safe, reserve)
    return {
        "slack": slack,
        "safe_bunks": safe,
        "reserve": reserve,
        **buckets,
    }


def all_economy(ref_today: date | None = None) -> list[dict[str, Any]]:
    return [economy_for(s["code"], ref_today) for s in config.subjects()]
