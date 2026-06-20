"""Notebox (Y-slot notes) and Bunk Log (N-slot reasons/notes) stores.

Both are derived journals populated during logging. Keeping them in their own
files (as the PRD specifies) makes the notes/bunks views and CSV export trivial.
"""

from __future__ import annotations

from typing import Any

from . import storage


def add_note(date: str, time: str, subject: str, note: str) -> None:
    data = storage.load("notebox")
    data.setdefault("notes", []).append(
        {"date": date, "time": time, "subject": subject, "note": note}
    )
    storage.save("notebox", data)


def notes(subject: str | None = None) -> list[dict[str, Any]]:
    items = storage.load("notebox").get("notes", [])
    if subject:
        items = [n for n in items if n["subject"].lower() == subject.lower()]
    return items


def add_bunk(date: str, time: str, subject: str, reason: str, note: str) -> None:
    data = storage.load("bunklog")
    data.setdefault("entries", []).append(
        {
            "date": date,
            "time": time,
            "subject": subject,
            "reason": reason,
            "note": note,
        }
    )
    storage.save("bunklog", data)


def bunks(subject: str | None = None) -> list[dict[str, Any]]:
    items = storage.load("bunklog").get("entries", [])
    if subject:
        items = [b for b in items if b["subject"].lower() == subject.lower()]
    return items


def remove_for_date(d: str) -> None:
    """Drop journal entries for a date (used when a day is re-logged)."""
    nb = storage.load("notebox")
    nb["notes"] = [n for n in nb.get("notes", []) if n["date"] != d]
    storage.save("notebox", nb)
    bl = storage.load("bunklog")
    bl["entries"] = [b for b in bl.get("entries", []) if b["date"] != d]
    storage.save("bunklog", bl)
