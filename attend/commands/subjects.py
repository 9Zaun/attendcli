"""`attend subjects` — list configured subjects with alias, code, credits, reserve."""

from __future__ import annotations

from rich.table import Table

from .. import config
from ..console import console, info


def cmd_subjects(args) -> int:
    subs = config.subjects()
    if not subs:
        info("No subjects configured.")
        return 0

    table = Table(title="Subjects", header_style="bold")
    for col in ["Alias", "Code", "Name", "Credits", "Reserve"]:
        table.add_column(col)
    for s in subs:
        table.add_row(
            s.get("alias") or s["code"],
            s["code"],
            s.get("name", ""),
            str(s.get("credits", "—")),
            str(s.get("reserve", 0)),
        )
    console.print(table)
    return 0
