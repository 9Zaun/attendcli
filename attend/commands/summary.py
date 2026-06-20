"""`attend summary` — compact one-screen "where am I" overview."""

from __future__ import annotations

from rich.table import Table

from .. import attendance, config, storage, tasks_store, weeks
from ..console import console, info, warn
from ..dates import parse_iso, today, week_number


def cmd_summary(args) -> int:
    sem = config.semester()
    label = sem.get("label", "Semester")
    start = parse_iso(sem["start"])
    pre = today() < start

    if pre:
        console.rule(f"{label} — Pre-semester (starts {sem['start']})")
    else:
        wn = week_number(today(), start)
        console.rule(f"{label} — Week {wn}")

    # Attendance per subject
    table = Table(title="Attendance", header_style="bold")
    for col in ["Subject", "Attended", "Missed", "Slack", "Spendable", "Status"]:
        table.add_column(col)
    for eco in attendance.all_economy():
        slack = eco["slack"]
        sign = "+" if slack >= 0 else ""
        if eco["below_75"]:
            st = "[red]BELOW 75%[/red]"
        elif eco["spendable_bunks"] == 0:
            st = "[yellow]no bunks[/yellow]"
        else:
            st = "[green]ok[/green]"
        table.add_row(
            eco["alias"], str(eco["P"]), str(eco["A"]),
            f"{sign}{slack}", str(eco["spendable_bunks"]), st,
        )
    console.print(table)

    # Tasks completed vs total (excluding cancelled from the denominator)
    items = tasks_store.items()
    done = sum(1 for i in items if i.get("status") == tasks_store.DONE)
    pending = sum(1 for i in items if i.get("status") == tasks_store.PENDING)
    total_active = done + pending
    console.print(
        f"\n[bold]Tasks:[/bold] {done} done / {total_active} active "
        f"({pending} pending)"
    )

    # Marks logged count
    marks_count = len(storage.load("marks").get("entries", []))
    console.print(f"[bold]Marks logged:[/bold] {marks_count} component(s)")

    # Current week goal
    if not pre:
        wn = week_number(today(), start)
        wk = weeks.get_week(wn)
        goal = (wk or {}).get("goal", "")
        console.print(f"[bold]Week {wn} goal:[/bold] {goal or '(none set)'}")
    else:
        info("Week goals begin once the semester starts.")
    return 0
