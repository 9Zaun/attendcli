"""Crunch scheduler state and algorithm.

State shape (``schedule.json``):
  {
    "current":  {"days": {ISODATE: [task_id, ...]}, "unscheduled": [...],
                 "generated_at": ISO, "params": {...}} | null,
    "previous": <same shape> | null,
    "stale": bool
  }

The stale flag is set whenever a task's priority/due/status/fixed flag changes so the
tasks view can show a ``[!]`` reminder until the user re-runs ``attend schedule --crunch``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import config, scoring, storage, tasks_store
from .dates import parse_iso, to_iso, today, weekday_short


def load() -> dict[str, Any]:
    return storage.load("schedule")


def save(data: dict[str, Any]) -> None:
    storage.save("schedule", data)


def is_stale() -> bool:
    return bool(load().get("stale"))


def has_plan() -> bool:
    return load().get("current") is not None


def mark_stale() -> None:
    data = load()
    if data.get("current") is not None:
        data["stale"] = True
        save(data)


# --------------------------------------------------------------------------- #
# Greedy scheduler
# --------------------------------------------------------------------------- #


def _capacity_cost(item: dict, mode: str) -> int:
    """How much of a day's budget an item consumes."""
    if mode == "task_count":
        return 1
    # priority_sum: a task's priority (which embeds effort) is its cost.
    return int(item.get("priority", 1))


# Sentinel reference date for tasks that have none (sorts after every real one).
_FAR_REF = "9999-12-31"


def _ref_iso(task: dict, id_map: dict[str, dict]) -> str | None:
    """The date (``YYYY-MM-DD``) that drives a task's urgency, or None.

    A linked task inherits its deadline/event's date; the link wins over any
    ``due`` on the task itself (see ``scoring.reference_date``).
    """
    ref = scoring.reference_date(task, id_map)
    return ref[:10] if ref else None


def _eligible_days(day_list: list, due, base) -> list:
    """Working days a task may be placed on.

    A linked/dated task must finish **strictly before** its reference date, so
    the reference date itself (the exam/presentation day) is excluded — eligible
    days are ``base <= d < due``. A task with no reference date may use the whole
    horizon.
    """
    if due is None:
        return list(day_list)
    return [d for d in day_list if base <= d < due]


def _choose_day(eligible: list, used: dict, cost: int, capacity: int):
    """Pick the day to place a task on.

    Capacity is a *soft* target: prefer the least-loaded eligible day that still
    fits under capacity (this spreads work evenly while staying within budget).
    Only when every eligible day is already full do we overflow — onto the
    least-loaded eligible day anyway, so the unavoidable excess is spread across
    the window rather than dumped on one day. Ties always break toward the
    earliest day. Returns None only when there is no eligible day at all.
    """
    if not eligible:
        return None
    under = [d for d in eligible if used[to_iso(d)] + cost <= capacity]
    pool = under or eligible
    return min(pool, key=lambda d: (used[to_iso(d)], d))


def generate() -> dict[str, Any]:
    """Produce a fresh day-by-day plan from pending tasks.

    Strategy (deadline-aware balanced spreading with a soft capacity):

    1. Fixed tasks are pinned to their ``fixed_date`` first (always, even above
       capacity; never moved by the greedy step).
    2. Each non-fixed task's reference date is its linked deadline/event date if
       else its own ``due``. Eligible days are ``today <= day < reference`` —
       the exam/presentation day is a no-work day for tasks tied to it.
    3. Non-fixed tasks are placed earliest-deadline-first (nearer reference dates reserve
       their smaller windows before farther ones), with higher score winning
       within the same date and undated tasks placed last.
    4. Each non-fixed task goes on the least-loaded eligible day that stays within
       capacity; if all eligible days are full, it overflows onto the
       least-loaded eligible day (capacity is a soft target — never violated
       unless finishing on time is otherwise impossible, and then the excess is
       spread, never crammed onto a single day).
    5. Overload is detected two ways and recorded for transparency: per-day
       (any planned day above capacity) and per-deadline (when the work due
       before a reference date cannot fit in capacity x available days).

    Tasks with no eligible day at all (reference date is today/past) are flagged
    as unscheduled.
    """
    s = config.settings()
    mode = s["crunch_capacity_mode"]
    capacity = int(s["crunch_daily_capacity"])
    skip_weekends = bool(s["crunch_skip_weekends"])
    horizon = int(s["crunch_horizon_days"])

    base = today()
    id_map = tasks_store.by_id_map()

    # Only actual work items are scheduled (deadlines/events are dates, not work).
    pending_tasks = tasks_store.pending(kind="task")
    fixed_tasks = [t for t in pending_tasks if tasks_store.is_fixed(t)]
    free_tasks = [t for t in pending_tasks if not tasks_store.is_fixed(t)]

    # Build the candidate working-day list.
    day_list: list = []
    for offset in range(horizon + 1):
        d = base + timedelta(days=offset)
        if skip_weekends and weekday_short(d) in ("Sat", "Sun"):
            continue
        day_list.append(d)

    used: dict[str, int] = {to_iso(d): 0 for d in day_list}
    days: dict[str, list[str]] = {to_iso(d): [] for d in day_list}
    unscheduled: list[str] = []

    # Step 1: pin fixed tasks to their fixed date (always, even above capacity).
    for task in fixed_tasks:
        pin = tasks_store.pin_date(task, id_map)
        if not pin:
            unscheduled.append(task["id"])
            continue
        key = pin
        if key not in days:
            days[key] = []
            used[key] = 0
        days[key].append(task["id"])
        used[key] += _capacity_cost(task, mode)

    # Step 2: earliest-deadline-first greedy for all non-fixed tasks.
    ordered = sorted(
        free_tasks,
        key=lambda t: (_ref_iso(t, id_map) or _FAR_REF,
                       -scoring.score(t, id_map, base)),
    )

    for task in ordered:
        cost = _capacity_cost(task, mode)
        ref = _ref_iso(task, id_map)
        due = parse_iso(ref) if ref else None
        eligible = _eligible_days(day_list, due, base)
        chosen = _choose_day(eligible, used, cost, capacity)
        if chosen is None:
            unscheduled.append(task["id"])
            continue
        key = to_iso(chosen)
        days[key].append(task["id"])
        used[key] += cost

    overload = _detect_overload(
        pending_tasks, day_list, used, id_map, mode, capacity, base
    )

    # Drop empty days to keep the plan compact.
    days = {k: v for k, v in days.items() if v}

    return {
        "days": days,
        "unscheduled": unscheduled,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params": {
            "capacity_mode": mode,
            "daily_capacity": capacity,
            "skip_weekends": skip_weekends,
        },
        "overload": overload,
    }


def _detect_overload(pending_tasks, day_list, used, id_map, mode, capacity, base):
    """Summarize where/why the plan had to exceed the daily capacity.

    ``days``      — ISO dates whose planned load exceeds capacity.
    ``deadlines`` — reference dates for which the work that *must* finish before
                    them cannot fit in ``capacity x (available days before it)``;
                    this is the root cause of any unavoidable overload.
    """
    overloaded_days = sorted(k for k, load in used.items() if load > capacity)

    deadlines: list[dict] = []
    refs = sorted({r for t in pending_tasks if (r := _ref_iso(t, id_map))})
    for r in refs:
        rdate = parse_iso(r)
        days_before = sum(1 for d in day_list if base <= d < rdate)
        slots = capacity * days_before
        required = sum(
            _capacity_cost(t, mode) for t in pending_tasks
            if (tr := _ref_iso(t, id_map)) and tr <= r
        )
        if required > slots:
            marker_ids = [
                it["id"] for it in tasks_store.items()
                if it.get("status") == tasks_store.PENDING
                and it.get("kind") in ("deadline", "event")
                and (mr := _ref_iso(it, id_map)) and mr == r
            ]
            deadlines.append({
                "ref": r,
                "required": required,
                "slots": slots,
                "days_before": days_before,
                "marker_ids": marker_ids,
            })

    return {"days": overloaded_days, "deadlines": deadlines}


def commit(new_plan: dict[str, Any]) -> None:
    """Store a new plan, pushing the existing one into ``previous`` for undo."""
    data = load()
    data["previous"] = data.get("current")
    data["current"] = new_plan
    data["stale"] = False
    save(data)


def undo() -> bool:
    """Restore the previous plan. Returns False if there's nothing to undo.

    A single level of undo is supported (per the README): restoring consumes the
    saved previous plan, so a second consecutive ``--undo`` reports that there is
    nothing left to revert instead of ping-ponging between two states.
    """
    data = load()
    prev = data.get("previous")
    if prev is None:
        return False
    data["current"] = prev
    data["previous"] = None
    data["stale"] = False
    save(data)
    return True


def move(task_id: str, date_iso: str) -> bool:
    """Manually move a task to a given day in the current plan."""
    data = load()
    cur = data.get("current")
    if cur is None:
        return False
    canon = None
    task = tasks_store.find(task_id)
    if task is None:
        return False
    canon = task["id"]

    # Remove from wherever it currently sits (and from unscheduled).
    for k in list(cur.get("days", {}).keys()):
        cur["days"][k] = [t for t in cur["days"][k] if t != canon]
    cur["days"] = {k: v for k, v in cur["days"].items() if v}
    cur["unscheduled"] = [t for t in cur.get("unscheduled", []) if t != canon]

    cur.setdefault("days", {}).setdefault(date_iso, []).append(canon)
    data["current"] = cur
    save(data)
    # Keep a fixed task's pin in sync with manual moves.
    if tasks_store.is_fixed(task):
        tasks_store.update(canon, fixed_date=date_iso)
    return True
