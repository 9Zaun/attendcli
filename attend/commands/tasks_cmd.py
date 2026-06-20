"""Task/deadline/event commands: add, tasks, done, cancel, show, schedule, fix."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from rich.table import Table

from .. import config, prompts, schedule, scoring, tasks_store
from ..console import console, error, info, success, warn
from ..dates import parse_date_arg, parse_iso, to_iso, today, weekday_short


def _deprecation_warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def _subject_label(code: str) -> str:
    return config.alias_for(code) if code else "—"


def _ask_due_in_semester(message: str) -> str:
    """Ask for a date, re-prompting if the user declines the semester warning."""
    while True:
        d_iso = prompts.ask_date(message)
        if prompts.confirm_in_semester(d_iso):
            return d_iso


def dispatch(cmd: str, args) -> int:
    if cmd == "add":
        return cmd_add(args)
    if cmd == "tasks":
        return cmd_tasks(args)
    if cmd == "done":
        return cmd_done(args)
    if cmd == "cancel":
        return cmd_cancel(args)
    if cmd == "show":
        return cmd_show(args)
    if cmd == "schedule":
        return cmd_schedule(args)
    if cmd == "crunch":
        return cmd_crunch(args)
    if cmd == "fix":
        return cmd_fix(args)
    if cmd == "unfix":
        return cmd_unfix(args)
    return 1


# --------------------------------------------------------------------------- #
# attend add
# --------------------------------------------------------------------------- #


def cmd_add(args) -> int:
    s = config.settings()
    pmin, pmax = s["priority_min"], s["priority_max"]

    kind = prompts.ask_choice(
        "Kind", choices=["task", "deadline", "event"], default="task"
    )

    subject_raw = prompts.ask_optional("Subject alias/code (optional)")
    if subject_raw:
        resolved = config.find_subject(subject_raw)
        if resolved:
            subject = resolved["code"]
        else:
            warn(f"  '{subject_raw}' isn't a known subject; storing it as-is.")
            subject = subject_raw
    else:
        subject = ""

    title = prompts.ask_required("Title")

    due = None
    event_time = None
    linked_to = None
    if kind == "deadline":
        due = _ask_due_in_semester("Due date (e.g. 22-06-2026)")
    elif kind == "event":
        ev_date = _ask_due_in_semester("Event date (e.g. 20-06-2026)")
        ev_time = prompts.ask_optional("Event time (e.g. 10:00 or 2:30 PM, optional)")
        if ev_time:
            try:
                ev_time = prompts.parse_time(ev_time)
                event_time = f"{ev_date} {ev_time}"
            except prompts.TimeParseError as exc:
                warn(f"  {exc} — storing date only.")
                event_time = ev_date
        else:
            event_time = ev_date
    else:  # task
        link = prompts.ask_optional("Link to existing item id (optional, e.g. t3)")
        if link:
            if tasks_store.find(link):
                linked_to = tasks_store.find(link)["id"]
            else:
                warn(f"  No item '{link}'; ignoring link.")
        if not linked_to:
            raw_due = prompts.ask_optional("Due date (optional, e.g. 25-06-2026)")
            if raw_due:
                try:
                    parsed = to_iso(prompts.parse_date(raw_due))
                except prompts.DateParseError as exc:
                    warn(f"  {exc} — leaving this task without a due date.")
                    parsed = None
                if parsed and prompts.confirm_in_semester(parsed):
                    due = parsed

    priority = prompts.ask_int(
        f"Priority ({pmin}-{pmax}, {pmax}=most important/effort)",
        default=pmin,
        min_v=pmin,
        max_v=pmax,
    )

    tags_raw = prompts.ask_optional("Tags (comma-separated, optional)")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    notes = prompts.ask_optional("Notes (optional)")

    item = {
        "id": tasks_store.next_id(),
        "kind": kind,
        "subject": subject or "",
        "title": title,
        "due": due,
        "event_time": event_time,
        "linked_to": linked_to,
        "priority": priority,
        "tags": tags,
        "status": tasks_store.PENDING,
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks_store.add(item)
    schedule.mark_stale()
    success(f"Added {item['id']}: {title}.")
    return 0


# --------------------------------------------------------------------------- #
# attend tasks
# --------------------------------------------------------------------------- #


def _render_status_list(items: list[dict], heading: str, sort_key,
                        when_field: str = "completed_at") -> int:
    if not items:
        info(f"No {heading.lower()} items.")
        return 0
    id_map = tasks_store.by_id_map()
    table = Table(title=heading, header_style="bold")
    for col in ["ID", "Kind", "Subject", "Title", "Ref date", "P", "When", "Notes"]:
        table.add_column(col)
    for it in sorted(items, key=sort_key):
        ref = scoring.reference_date(it, id_map) or "—"
        when = it.get(when_field) or "—"
        note_mark = "✎" if (it.get("notes") or "").strip() else ""
        table.add_row(
            it["id"], it["kind"], _subject_label(it.get("subject") or ""),
            it["title"], ref, str(it["priority"]), when, note_mark,
        )
    console.print(table)
    return 0


def cmd_tasks(args) -> int:
    # Status filters take precedence and show their own views.
    if getattr(args, "done", False):
        done_items = [i for i in tasks_store.items() if i.get("status") == tasks_store.DONE]
        return _render_status_list(
            done_items, "Completed tasks",
            sort_key=lambda i: i.get("completed_at") or "",
        )
    if getattr(args, "cancelled", False):
        cancelled_items = [
            i for i in tasks_store.items() if i.get("status") == tasks_store.CANCELLED
        ]
        return _render_status_list(
            cancelled_items, "Cancelled tasks",
            sort_key=lambda i: i.get("cancelled_at") or i.get("created_at") or "",
            when_field="cancelled_at",
        )

    subj_arg = getattr(args, "subject", None)
    if subj_arg:
        subj_arg = config.resolve_code(subj_arg) or subj_arg
    pool = tasks_store.pending(
        kind=getattr(args, "kind", None),
        subject=subj_arg,
        tag=getattr(args, "tag", None),
    )
    ordered = tasks_store.sorted_by_score(pool)
    if not ordered:
        info("No pending items match.")
        return 0

    # The stale banner is only meaningful when the view actually contains
    # schedulable tasks; deadlines/events are never in the crunch plan.
    has_tasks = any(it["kind"] == "task" for it in ordered)
    stale = schedule.is_stale() and has_tasks
    id_map = tasks_store.by_id_map()

    title = "Tasks — by priority × urgency"
    if stale:
        title += r"  \[!] schedule stale (run `attend schedule --crunch`)"
    table = Table(title=title, header_style="bold")
    for col in ["", "ID", "Kind", "Subject", "Title", "Ref date", "P", "Score", "Tags", ""]:
        if col == "Ref date":
            table.add_column(col, no_wrap=True, min_width=10)
        elif col == "Kind":
            table.add_column(col, no_wrap=True, min_width=8)
        else:
            table.add_column(col)

    for it in ordered:
        ref = scoring.reference_date(it, id_map) or "—"
        sc = scoring.score(it, id_map)
        marker = r"[yellow]\[!][/yellow]" if (stale and it["kind"] == "task") else ""
        note_mark = "[blue]✎[/blue]" if (it.get("notes") or "").strip() else ""
        fixed_mark = " [magenta](fixed)[/magenta]" if tasks_store.is_fixed(it) else ""
        tags = " ".join(f"#{t}" for t in it.get("tags", []))
        table.add_row(
            marker,
            it["id"],
            it["kind"],
            _subject_label(it.get("subject") or ""),
            it["title"] + fixed_mark,
            ref,
            str(it["priority"]),
            f"{sc:.1f}",
            tags,
            note_mark,
        )
    console.print(table)
    if any((it.get("notes") or "").strip() for it in ordered):
        info("[dim]✎ = has notes (view with `attend show ID`)[/dim]")
    return 0


# --------------------------------------------------------------------------- #
# attend done / cancel
# --------------------------------------------------------------------------- #


def _set_status(item_id: str, status: str, verb: str) -> int:
    item = tasks_store.find(item_id)
    if not item:
        error(f"No item with id '{item_id}'.")
        return 1
    # Don't silently re-process an already-closed item (which would, for the
    # done→done case, overwrite the original completion date).
    current = item.get("status")
    if current == status:
        error(f"{item['id']} is already marked {verb}.")
        return 1
    if current in (tasks_store.DONE, tasks_store.CANCELLED):
        state = "completed" if current == tasks_store.DONE else "cancelled"
        error(f"{item['id']} is already {state}.")
        return 1
    extra = {}
    if status == tasks_store.DONE:
        extra["completed_at"] = to_iso(parse_date_arg(None))
    elif status == tasks_store.CANCELLED:
        extra["cancelled_at"] = to_iso(parse_date_arg(None))
    tasks_store.update(item["id"], status=status, **extra)
    schedule.mark_stale()
    success(f"{item['id']} ({item['title']}) marked {verb}.")
    return 0


def cmd_done(args) -> int:
    return _set_status(args.id, tasks_store.DONE, "done")


def cmd_cancel(args) -> int:
    return _set_status(args.id, tasks_store.CANCELLED, "cancelled")


# --------------------------------------------------------------------------- #
# attend show
# --------------------------------------------------------------------------- #


def cmd_show(args) -> int:
    item = tasks_store.find(args.id)
    if not item:
        error(f"No item with id '{args.id}'.")
        return 1
    id_map = tasks_store.by_id_map()
    is_open = item.get("status") == tasks_store.PENDING
    console.rule(f"{item['id']} · {item['title']}")
    info(f"  Kind:       {item['kind']}")
    info(f"  Subject:    {_subject_label(item.get('subject') or '')}")
    info(f"  Status:     {item['status']}")
    info(f"  Priority:   {item['priority']}")

    # Flag a past-due item that is still open.
    overdue = False
    if is_open:
        ref_iso = scoring.reference_date(item, id_map)
        if ref_iso and parse_iso(ref_iso[:10]) < today():
            overdue = True

    if item.get("due"):
        marker = "  [bold red]⚠ OVERDUE[/bold red]" if overdue else ""
        info(f"  Due:        {item['due']}{marker}")
    if item.get("event_time"):
        marker = "  [bold red]⚠ OVERDUE[/bold red]" if overdue else ""
        info(f"  Event:      {item['event_time']}{marker}")
    if item.get("linked_to"):
        info(f"  Linked to:  {item['linked_to']}")
    ref = scoring.reference_date(item, id_map)
    info(f"  Ref date:   {ref or '—'}")
    if item.get("kind") == "task":
        if tasks_store.is_fixed(item):
            pin = tasks_store.pin_date(item, id_map) or "—"
            info(f"  Fixed:      yes (pinned to {pin})")
        else:
            info("  Fixed:      no")
    # Score is a planning metric; it's meaningless for closed items.
    if is_open:
        info(f"  Score:      {scoring.score(item, id_map):.2f}")
    else:
        info("  Score:      [dim]— (not applicable for "
             f"{item['status']} items)[/dim]")
    info(f"  Tags:       {', '.join(item.get('tags', [])) or '—'}")
    info(f"  Created:    {item.get('created_at', '—')}")
    if item.get("completed_at"):
        info(f"  Completed:  {item['completed_at']}")
    if item.get("cancelled_at"):
        info(f"  Cancelled:  {item['cancelled_at']}")
    info(f"  Notes:      {item.get('notes') or '—'}")
    return 0


# --------------------------------------------------------------------------- #
# attend schedule (primary) / attend crunch (deprecated wrapper)
# --------------------------------------------------------------------------- #


def _plan_day_for(task_id: str) -> str | None:
    """Return the ISO date a task sits on in the current plan, if any."""
    cur = schedule.load().get("current") or {}
    for day_iso, ids in cur.get("days", {}).items():
        if task_id in ids:
            return day_iso
    return None


def _run_planner() -> None:
    """Generate a fresh plan and open the board."""
    plan = schedule.generate()
    schedule.commit(plan)
    success("Regenerated schedule plan.")
    _open_board()


def cmd_schedule(args) -> int:
    if getattr(args, "schedule_command", None) == "move":
        return _schedule_move(args)

    if getattr(args, "undo", False):
        if schedule.undo():
            success("Reverted to previous schedule plan.")
            _open_board()
        else:
            warn("No previous plan to undo to.")
        return 0

    if getattr(args, "crunch", False):
        _run_planner()
        return 0

    # Read-only view: never create or modify a plan.
    if not schedule.has_plan():
        info(
            "No plan yet — showing deadlines only. "
            "Run `attend schedule --crunch` to plan tasks."
        )
    _open_board()
    return 0


def cmd_crunch(args) -> int:
    """Deprecated entry point; delegates to ``cmd_schedule`` equivalents."""
    if getattr(args, "crunch_command", None) == "move":
        _deprecation_warn(
            "`attend crunch move` is deprecated. Use `attend schedule move` instead."
        )
        return _schedule_move(args)

    if getattr(args, "undo", False):
        _deprecation_warn(
            "`attend crunch --undo` is deprecated. Use `attend schedule --undo` instead."
        )
        args.undo = True
        return cmd_schedule(args)

    if getattr(args, "replan", False):
        _deprecation_warn(
            "`attend crunch --replan` is deprecated. Use `attend schedule --crunch` instead."
        )
        args.crunch = True
        return cmd_schedule(args)

    _deprecation_warn(
        "`attend crunch` is deprecated. Use `attend schedule --crunch` instead."
    )
    args.crunch = True
    return cmd_schedule(args)


def _schedule_move(args) -> int:
    task = tasks_store.find(args.task_id)
    if not task:
        error(f"No item with id '{args.task_id}'.")
        return 1

    # Only schedulable, still-open tasks can be moved on the board.
    if task.get("kind") != "task":
        error(f"{task['id']} is a {task.get('kind')}, not a schedulable task.")
        return 1
    if task.get("status") == tasks_store.DONE:
        error(f"{task['id']} is already completed.")
        return 1
    if task.get("status") == tasks_store.CANCELLED:
        error(f"{task['id']} is cancelled.")
        return 1

    try:
        date_iso = to_iso(prompts.parse_date(args.date))
    except prompts.DateParseError as exc:
        error(str(exc))
        return 1

    # Don't allow scheduling work into the past.
    if parse_iso(date_iso) < today():
        error(f"Can't move {task['id']} to {date_iso}: that date is in the past.")
        return 1

    if not schedule.has_plan():
        error("No current plan. Run `attend schedule --crunch` first.")
        return 1
    schedule.move(task["id"], date_iso)  # persists; deliberately not marked stale
    success(f"Moved {task['id']} to {date_iso}.")
    _open_board(window_start=parse_iso(date_iso))
    return 0


# --------------------------------------------------------------------------- #
# attend fix / attend unfix
# --------------------------------------------------------------------------- #


def cmd_fix(args) -> int:
    item = tasks_store.find(args.id)
    if not item:
        error(f"No item with id '{args.id}'.")
        return 1
    if item.get("kind") != "task":
        error(f"{item['id']} is a {item.get('kind')}; only tasks can be fixed.")
        return 1
    if item.get("status") != tasks_store.PENDING:
        error(f"{item['id']} is {item.get('status')}; only pending tasks can be fixed.")
        return 1

    id_map = tasks_store.by_id_map()
    ref = scoring.reference_date(item, id_map)
    if not ref:
        error(
            f"Cannot fix {item['id']}: no linked deadline/event or due date to pin to."
        )
        return 1

    # Pin to the task's current plan day when scheduled; otherwise use the
    # reference date (linked deadline/event or own due).
    pin = _plan_day_for(item["id"]) or ref[:10]
    tasks_store.update(item["id"], fixed=True, fixed_date=pin)
    schedule.mark_stale()
    success(f"{item['id']} fixed to {pin} (planner will not move it).")
    return 0


def cmd_unfix(args) -> int:
    item = tasks_store.find(args.id)
    if not item:
        error(f"No item with id '{args.id}'.")
        return 1
    if not tasks_store.is_fixed(item):
        error(f"{item['id']} is not fixed.")
        return 1
    tasks_store.update(item["id"], fixed=False, fixed_date=None)
    schedule.mark_stale()
    success(f"{item['id']} unfixed — planner may reschedule it.")
    return 0


# --------------------------------------------------------------------------- #
# 7-day Kanban board
# --------------------------------------------------------------------------- #


def _plan_task_ids(plan: dict) -> set[str]:
    """Task IDs the saved plan already references (scheduled or unschedulable)."""
    ids: set[str] = set(plan.get("unscheduled", []))
    for day_ids in plan.get("days", {}).values():
        ids.update(day_ids)
    return ids


def _new_since_plan(plan: dict) -> list[dict]:
    """Pending tasks not yet represented anywhere in the saved plan.

    These were added (or re-opened) after the last ``schedule --crunch`` and are
    shown separately so ``attend schedule`` reflects the full task list without
    silently re-running the planner.
    """
    if not schedule.has_plan():
        return []
    known = _plan_task_ids(plan)
    delta = [
        t for t in tasks_store.pending(kind="task")
        if t["id"] not in known
    ]
    return tasks_store.sorted_by_score(delta)


def _split_new_tasks(
    new_tasks: list[dict], window_start, id_map: dict[str, dict]
) -> tuple[dict[str, list[dict]], list[dict], set[str]]:
    """Split new-since-plan tasks into window column placement vs footer.

    Returns ``(by_day, undated, column_new_ids)`` where ``by_day`` maps ISO dates
    within the 7-day window to tasks shown visually (not in the saved plan).
    """
    window_end = window_start + timedelta(days=6)
    by_day: dict[str, list[dict]] = {}
    undated: list[dict] = []
    column_ids: set[str] = set()
    for t in new_tasks:
        ref = scoring.reference_date(t, id_map)
        if not ref:
            undated.append(t)
            continue
        ref_d = parse_iso(ref[:10])
        if window_start <= ref_d <= window_end:
            iso = to_iso(ref_d)
            by_day.setdefault(iso, []).append(t)
            column_ids.add(t["id"])
    return by_day, tasks_store.sorted_by_score(undated), column_ids


def _render_task_line(it: dict, *, suffix: str = "") -> None:
    """One-line task summary for board footer sections."""
    id_map = tasks_store.by_id_map()
    ref = scoring.reference_date(it, id_map) or "—"
    label = config.alias_for(it["subject"]) if it.get("subject") else it["title"]
    fixed = " 📌" if tasks_store.is_fixed(it) else ""
    console.print(
        f"  [cyan]{it['id']}[/cyan]{fixed} {label} "
        f"[dim]({it['title']}, ref {ref}){suffix}[/dim]"
    )


def _overdue_pending() -> list[dict]:
    """Pending tasks whose due/reference date is strictly before today."""
    id_map = tasks_store.by_id_map()
    base = today()
    result = []
    for it in tasks_store.pending(kind="task"):
        ref = scoring.reference_date(it, id_map)
        if ref and parse_iso(ref[:10]) < base:
            result.append(it)
    return result


def _pending_markers() -> list[dict]:
    """Pending deadlines and events (non-movable date markers on the board)."""
    return [
        it for it in tasks_store.items()
        if it.get("status") == tasks_store.PENDING
        and it.get("kind") in ("deadline", "event")
    ]


def _marker_cell(items: list[dict]) -> str:
    if not items:
        return "[dim]—[/dim]"
    lines = []
    for it in items:
        glyph = "◆" if it["kind"] == "deadline" else "★"
        label = config.alias_for(it["subject"]) if it.get("subject") else it["title"][:18]
        lines.append(f"[magenta]{glyph} {it['id']}[/magenta] {label}\n  [dim]{it['title'][:18]}[/dim]")
    return "\n".join(lines)


def _day_load(items: list[dict], mode: str) -> int:
    """Planned capacity used by a day's tasks (count, or summed priority)."""
    if mode == "task_count":
        return len(items)
    return sum(int(it.get("priority", 1)) for it in items)


def _build_board(
    plan: dict,
    window_start,
    overdue: list[dict],
    *,
    new_by_day: dict[str, list[dict]] | None = None,
    new_column_ids: set[str] | None = None,
):
    id_map = tasks_store.by_id_map()
    base = today()
    s = config.settings()
    mode = s["crunch_capacity_mode"]
    capacity = int(s["crunch_daily_capacity"])
    overloaded_isos: list[str] = []
    new_by_day = new_by_day or {}
    new_column_ids = new_column_ids or set()

    table = Table(show_lines=True, header_style="bold", expand=False)

    markers = _pending_markers()
    # Overdue markers (deadlines/events whose date already passed) share the
    # OVERDUE column with overdue tasks.
    overdue_markers = [
        m for m in markers
        if (ref := scoring.reference_date(m, id_map)) and parse_iso(ref[:10]) < base
    ]

    # head, task_items, marker_items
    columns: list[tuple[str, list[dict], list[dict]]] = []

    if overdue or overdue_markers:
        columns.append((
            "[red]OVERDUE[/red]",
            tasks_store.sorted_by_score(overdue),
            overdue_markers,
        ))

    for offset in range(7):
        d = window_start + timedelta(days=offset)
        iso = to_iso(d)
        ids = plan.get("days", {}).get(iso, [])
        # Filter to still-pending tasks: a stale plan may reference items that
        # have since been completed/cancelled, which must not show as "to do".
        day_items = tasks_store.sorted_by_score([
            id_map[i] for i in ids
            if i in id_map
            and id_map[i].get("status") == tasks_store.PENDING
            and id_map[i].get("kind") == "task"
        ])
        # Visual-only: new tasks whose reference date falls on this column.
        extras = new_by_day.get(iso, [])
        if extras:
            day_items = tasks_store.sorted_by_score(day_items + extras)
        day_markers = [
            m for m in markers
            if (ref := scoring.reference_date(m, id_map)) and ref[:10] == iso
        ]
        is_today = d == base
        head = f"{weekday_short(d)}\n{d.strftime('%b %d')}"
        if is_today:
            head = f"[bold green]TODAY[/bold green]\n[green]{d.strftime('%b %d')}[/green]"
        load = _day_load(
            [it for it in day_items if it["id"] not in new_column_ids], mode
        )
        if load > capacity:
            overloaded_isos.append(iso)
            head += f"\n[red]⚠ {load}/{capacity}[/red]"
        columns.append((head, day_items, day_markers))

    for head, _, _ in columns:
        table.add_column(head, vertical="top")

    def cell(items: list[dict]) -> str:
        if not items:
            return "[dim]—[/dim]"
        lines = []
        for it in items:
            is_new = it["id"] in new_column_ids
            new_mark = " [yellow][!][/yellow]" if is_new else ""
            if it.get("subject"):
                head = config.alias_for(it["subject"])
                fixed = " [magenta]📌[/magenta]" if tasks_store.is_fixed(it) else ""
                sub = f"p{it['priority']} · {it['title'][:18]}"
            else:
                head = it["title"][:20]
                fixed = " [magenta]📌[/magenta]" if tasks_store.is_fixed(it) else ""
                sub = f"p{it['priority']}"
            lines.append(
                f"[cyan]{it['id']}[/cyan]{new_mark}{fixed} {head}\n  [dim]{sub}[/dim]"
            )
        return "\n".join(lines)

    table.add_row(*[cell(items) for _, items, _ in columns])
    # Second row: non-movable deadline/event markers (only when any exist).
    if any(mk for _, _, mk in columns):
        table.add_row(*[_marker_cell(mk) for _, _, mk in columns])
    return table, overloaded_isos


def _render_overload(plan: dict, overloaded_isos: list[str]) -> None:
    """Explain any days the plan had to push above the configured capacity."""
    overload = plan.get("overload") or {}
    deadlines = overload.get("deadlines", [])
    if not overloaded_isos and not deadlines:
        return

    id_map = tasks_store.by_id_map()
    s = config.settings()
    capacity = int(s["crunch_daily_capacity"])

    console.print("\n[bold yellow]⚠ ABOVE CAPACITY[/bold yellow] "
                  f"[dim](target {capacity}/day)[/dim]")
    if overloaded_isos:
        console.print("  Overloaded day(s): " + ", ".join(overloaded_isos) + ".")
    for r in deadlines:
        labels = []
        for mid in r.get("marker_ids", []):
            it = id_map.get(mid)
            if it:
                lab = config.alias_for(it["subject"]) if it.get("subject") else it["title"]
                labels.append(f"{lab} {it['title'][:24]}")
        why = "; ".join(labels) or "deadline"
        console.print(
            f"  [yellow]before {r['ref']}[/yellow]: {r['required']} units of work must "
            f"fit in {r['days_before']} day(s) × {capacity} = {r['slots']} slots "
            f"[dim]({why})[/dim]"
        )


def _render_board(window_start) -> None:
    plan = schedule.load().get("current") or {"days": {}, "unscheduled": []}
    overdue = _overdue_pending()
    overdue_ids = {i["id"] for i in overdue}
    id_map = tasks_store.by_id_map()

    console.rule("Schedule Board")
    stale = schedule.is_stale()
    new_tasks = _new_since_plan(plan)
    new_by_day, _, new_column_ids = _split_new_tasks(
        new_tasks, window_start, id_map
    )
    if stale:
        msg = (
            "[bold yellow]⚠ Schedule is stale — run 'attend schedule --crunch' "
            "to regenerate.[/bold yellow]"
        )
        if new_tasks:
            msg += (
                " [dim]New tasks appear with [!] in columns until you "
                "replan.[/dim]"
            )
        console.print(msg)
    if not schedule.has_plan():
        console.print(
            "[dim]read-only preview (no plan — run `attend schedule --crunch` to plan "
            "tasks)[/dim]"
        )
    console.print(
        f"[dim]window: {to_iso(window_start)} → "
        f"{to_iso(window_start + timedelta(days=6))}[/dim]"
    )

    board, overloaded_isos = _build_board(
        plan, window_start, overdue,
        new_by_day=new_by_day, new_column_ids=new_column_ids,
    )
    console.print(board)

    _render_overload(plan, overloaded_isos)

    # Unschedulable = unscheduled minus the overdue (those get their own column).
    unsched = [i for i in plan.get("unscheduled", []) if i not in overdue_ids]
    if unsched:
        console.print("\n[bold red]⚠ UNSCHEDULABLE (cannot fit before deadline):[/bold red]")
        for i in unsched:
            it = id_map.get(i)
            if it and it.get("status") == tasks_store.PENDING:
                _render_task_line(it)

    if new_tasks:
        console.print(
            "\n[bold cyan]UNSCHEDULED (NEW)[/bold cyan] "
            "[dim]— added since last plan; run `attend schedule --crunch` to place[/dim]"
        )
        for it in new_tasks:
            ref = scoring.reference_date(it, id_map)
            suffix = " (no date)" if not ref else ""
            _render_task_line(it, suffix=suffix)

    if _pending_markers():
        console.print(
            "[dim][magenta]◆[/magenta] deadline · [magenta]★[/magenta] event "
            "(non-movable date markers)[/dim]"
        )
    console.print(
        "\n[dim]→/l next 7 days · ←/h prev 7 days · q quit · "
        "move with `attend schedule move ID DATE` · "
        "pin with `attend fix ID`[/dim]"
    )


def _read_key() -> str:
    """Read a single keypress, normalizing arrow keys. Returns '' on EOF."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[C":
                return "right"
            if seq == "[D":
                return "left"
            return "other"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _open_board(window_start=None) -> None:
    window = window_start or today()

    # Non-interactive (piped/SSH script): render once and return cleanly.
    if not sys.stdin.isatty():
        _render_board(window)
        return

    while True:
        console.clear()
        _render_board(window)
        try:
            key = _read_key()
        except Exception:  # pragma: no cover - terminal quirks
            break
        if key in ("q", "\x03", "", "\r", "\n"):
            break
        if key in ("right", "l"):
            window = window + timedelta(days=7)
        elif key in ("left", "h"):
            window = window - timedelta(days=7)
