"""Notebox view: `attend notes`."""

from __future__ import annotations

from datetime import timedelta

from rich.table import Table

from .. import config, journals
from ..console import console, error, info
from ..dates import parse_date_arg, parse_iso, to_iso, week_start_date


def cmd_notes(args) -> int:
    subject = getattr(args, "subject", None)
    date_arg = getattr(args, "date", None)
    week = getattr(args, "week", None)

    if subject and not config.find_subject(subject):
        error(f"Unknown subject: {subject}")
        return 1

    entries = journals.notes(config.resolve_code(subject) if subject else None)

    if date_arg:
        d_iso = to_iso(parse_date_arg(date_arg))
        entries = [n for n in entries if n["date"] == d_iso]

    if week is not None:
        sem = config.semester()
        start = week_start_date(week, parse_iso(sem["start"]))
        end = start + timedelta(days=6)
        entries = [n for n in entries if start <= parse_iso(n["date"]) <= end]

    entries = sorted(entries, key=lambda n: (n["date"], n.get("time") or ""))
    if not entries:
        info("No notebox entries match.")
        return 0

    table = Table(title="Notebox", header_style="bold")
    for col in ["Date", "Time", "Subject", "Note"]:
        table.add_column(col)
    for n in entries:
        table.add_row(
            n["date"], n.get("time") or "",
            config.alias_for(n["subject"]), n.get("note") or "",
        )
    console.print(table)
    return 0
