"""Week box commands: weeks [N], week set, week reflect."""

from __future__ import annotations

from datetime import timedelta

from .. import config, scoring, tasks_store, weeks
from ..console import console, error, info, success, warn
from ..dates import parse_iso, to_iso, today, week_number


def dispatch(cmd: str, args) -> int:
    if cmd == "weeks":
        return cmd_weeks(args)
    if cmd == "week":
        return cmd_week(args)
    return 1


def _current_week_number() -> int:
    """Current 1-based week number, or 0 if we're pre-semester."""
    sem = config.semester()
    start = parse_iso(sem["start"])
    if today() < start:
        return 0
    return week_number(today(), start)


def _is_pre_semester() -> bool:
    return today() < parse_iso(config.semester()["start"])


def _week_state(wk: dict) -> str:
    """One of: 'current', 'done', 'past', 'future'."""
    start = parse_iso(wk["start_date"])
    end = start + timedelta(days=6)
    t = today()
    if start <= t <= end:
        return "current"
    if end < t:
        # Done only when a reflection has been written; otherwise just past.
        return "done" if (wk.get("reflection") or "").strip() else "past"
    return "future"


def _render_strip() -> None:
    cells = []
    for w in weeks.all_weeks():
        n = w["week_number"]
        state = _week_state(w)
        if state == "current":
            cells.append(f"[bold yellow][■{n}■][/bold yellow]")
        elif state == "done":
            cells.append(f"[green][✓{n}][/green]")
        elif state == "past":
            cells.append(f"[dim][·{n}·][/dim]")
        else:
            cells.append(f"[white][ {n} ][/white]")
    console.print(" ".join(cells))
    console.print(
        "[dim]legend: [/dim][bold yellow][■N■][/bold yellow]=current "
        "[green][✓N][/green]=done [dim][·N·][/dim]=past(no reflection) "
        "[white][ N ][/white]=upcoming"
    )


def _items_in_week(wk: dict) -> list[dict]:
    start = parse_iso(wk["start_date"])
    end = start + timedelta(days=6)
    id_map = tasks_store.by_id_map()
    result = []
    for it in tasks_store.items():
        ref = scoring.reference_date(it, id_map)
        if ref and start <= parse_iso(ref[:10]) <= end:
            result.append(it)
    return result


def _render_week_detail(n: int) -> int:
    wk = weeks.get_week(n)
    if not wk:
        error(f"No week {n} in this semester.")
        return 1

    start = parse_iso(wk["start_date"])
    end = start + timedelta(days=6)
    state = _week_state(wk)
    badge = {
        "current": "[bold yellow](current)[/bold yellow]",
        "done": "[green](done)[/green]",
        "past": "[dim](past, no reflection)[/dim]",
        "future": "[white](upcoming)[/white]",
    }[state]
    console.rule(f"Week {n}  ({to_iso(start)} → {to_iso(end)})  {badge}")
    info(f"  Goal:       {wk.get('goal') or 'not set'}")
    info(f"  Reflection: {wk.get('reflection') or 'not set'}")

    items = _items_in_week(wk)
    if items:
        console.print("\n[bold]Items this week[/bold]")
        for it in tasks_store.sorted_by_score(items):
            ref = scoring.reference_date(it, tasks_store.by_id_map()) or "—"
            console.print(
                f"  [cyan]{it['id']}[/cyan] {it['title']} "
                f"[dim]({it['kind']}, {it['status']}, {ref})[/dim]"
            )
    else:
        info("\n  (no tasks/deadlines/events fell in this week)")
    return 0


def cmd_weeks(args) -> int:
    n = getattr(args, "n", None)

    _render_strip()

    if n is None:
        return 0

    if n < 1:
        error(
            "Week boxes start from the semester start date. Use a week number "
            "of 1 or higher."
        )
        return 1
    return _render_week_detail(n)


_PRE_SEM_MSG = (
    "Week boxes start from the semester start date. You are currently in the "
    "pre-semester period."
)

_BAD_WEEK_MSG = "Week number must be 1 or greater."


def cmd_week(args) -> int:
    sub = getattr(args, "week_command", None)
    if sub == "set":
        return _week_set(args)
    if sub == "reflect":
        return _week_reflect(args)
    # No subcommand: read-only display of the current week's box. Editing is
    # done explicitly via `week set` / `week reflect`.
    return _week_current()


def _week_current() -> int:
    if _is_pre_semester():
        error(_PRE_SEM_MSG)
        return 1
    n = _current_week_number()
    _render_week_detail(n)
    info(
        "\n[dim]Edit with `attend week set %d \"goal\"` or "
        "`attend week reflect %d \"text\"`.[/dim]" % (n, n)
    )
    return 0


def _apply_week_field(n: int, field: str, value: str) -> None:
    data = weeks.load()
    for w in data["weeks"]:
        if w["week_number"] == n:
            w[field] = value
    weeks.save(data)


def _week_set(args) -> int:
    if args.n < 1:
        error(_BAD_WEEK_MSG)
        return 1
    wk = weeks.get_week(args.n)
    if not wk:
        error(f"No week {args.n} in this semester.")
        return 1
    _apply_week_field(args.n, "goal", args.text)
    success(f"Week {args.n} goal set.")
    return 0


def _week_reflect(args) -> int:
    raw = list(args.args or [])
    if not raw:
        error('Reflection text is required. Usage: attend week reflect [N] "text"')
        return 1
    if raw[0].isdigit():
        n = int(raw[0])
        text = " ".join(raw[1:])
    else:
        n = _current_week_number()
        text = " ".join(raw)
    if not text.strip():
        error('Reflection text is required. Usage: attend week reflect [N] "text"')
        return 1
    if n < 1:
        error(_BAD_WEEK_MSG)
        return 1
    wk = weeks.get_week(n)
    if not wk:
        error(f"No week {n} in this semester.")
        return 1
    _apply_week_field(n, "reflection", text)
    success(f"Week {n} reflection saved.")
    return 0
