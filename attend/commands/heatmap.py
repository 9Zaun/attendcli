"""Task-completion heatmap: `attend heatmap`.

Columns are semester weeks, rows are weekdays Mon-Sat, and each cell's intensity
reflects how many tasks were completed that day (attendance is a baseline, not
the productivity signal).
"""

from __future__ import annotations

from datetime import timedelta

from .. import config, tasks_store, weeks
from ..console import console, info
from ..dates import parse_iso, to_iso

ROWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# tasks-completed -> (char, style)
LEVELS = [
    ("·", "dim"),
    ("░", "green"),
    ("▒", "green"),
    ("▓", "bold green"),
    ("█", "bold green"),
]


def _cell(count: int):
    idx = min(count, len(LEVELS) - 1)
    return LEVELS[idx]


def completion_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in tasks_store.items():
        if it.get("status") == tasks_store.DONE and it.get("completed_at"):
            d = it["completed_at"][:10]
            counts[d] = counts.get(d, 0) + 1
    return counts


CELL_W = 3  # width of each day cell, matched by the week-number header
LABEL_W = 5  # left gutter for the weekday labels


def cmd_heatmap(args) -> int:
    all_weeks = weeks.all_weeks()
    if not all_weeks:
        info("No weeks defined.")
        return 0
    counts = completion_counts()

    console.print("[bold]Task completion heatmap[/bold]")

    # Header: each week number sits in a CELL_W-wide column so the grid lines up.
    header = " " * LABEL_W + "".join(
        f"{w['week_number']:>{CELL_W}}" for w in all_weeks
    )
    console.print(f"[dim]{header}[/dim]")

    for r, day_name in enumerate(ROWS):
        cells = []
        for w in all_weeks:
            d = parse_iso(w["start_date"]) + timedelta(days=r)
            n = counts.get(to_iso(d), 0)
            char, style = _cell(n)
            # Right-align the glyph within CELL_W so it sits under the week number.
            pad = " " * (CELL_W - 1)
            cells.append(f"{pad}[{style}]{char}[/{style}]")
        console.print(f"{day_name:<{LABEL_W}}" + "".join(cells))

    console.print(
        "\n[dim]legend:[/dim] "
        "[dim]·[/dim]=0 [green]░[/green]=1 [green]▒[/green]=2 "
        "[bold green]▓[/bold green]=3 [bold green]█[/bold green]=4+"
    )
    return 0
