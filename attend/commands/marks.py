"""Marks logging: `attend marks add SUBJECT` and `attend marks [SUBJECT]`.

Pure logging/reference — no CGPA or risk calculation, per the PRD. Credits are
surfaced only as a reminder of subject importance.
"""

from __future__ import annotations

from rich.table import Table

from .. import config, prompts, storage
from ..console import console, error, info, success


def _load() -> dict:
    return storage.load("marks")


def _save(data: dict) -> None:
    storage.save("marks", data)


def cmd_marks(args) -> int:
    rest = list(getattr(args, "rest", []) or [])
    if rest and rest[0].lower() == "add":
        if len(rest) < 2:
            error("Usage: attend marks add SUBJECT")
            return 1
        return _marks_add(rest[1])
    subject = rest[0] if rest else None
    return _marks_view(subject)


def _marks_add(subject_code: str) -> int:
    subject = config.find_subject(subject_code)
    if not subject:
        error(f"Unknown subject: {subject_code}")
        return 1

    component = prompts.ask_required("Component (e.g. midterm, quiz 1, project)")
    score = prompts.ask_required("Score (e.g. 18/20)")
    weightage = prompts.ask_optional("Weightage (optional, e.g. 20%)")
    notes = prompts.ask_optional("Notes (optional)")

    data = _load()
    data.setdefault("entries", []).append(
        {
            "subject": subject["code"],
            "component": component,
            "score": score,
            "weightage": weightage,
            "notes": notes,
        }
    )
    _save(data)
    success(f"Logged {subject.get('alias') or subject['code']} · {component}: {score}")
    return 0


def _marks_view(subject_code: str | None) -> int:
    if subject_code and not config.find_subject(subject_code):
        error(f"Unknown subject: {subject_code}")
        return 1

    entries = _load().get("entries", [])
    if subject_code:
        target = config.find_subject(subject_code)["code"]
        codes = [target]
    else:
        codes = config.subject_codes()

    any_shown = False
    for code in codes:
        subj = config.find_subject(code)
        rows = [e for e in entries if e["subject"].lower() == code.lower()]
        if not rows:
            continue
        any_shown = True
        alias = subj.get("alias") or subj["code"]
        table = Table(
            title=f"{alias} ({subj['code']}) — {subj['name']}  "
                  f"(credits: {subj.get('credits', '?')})",
            header_style="bold",
        )
        for col in ["Component", "Score", "Weightage", "Notes"]:
            table.add_column(col)
        for e in rows:
            table.add_row(
                e["component"], e["score"], e.get("weightage") or "—",
                e.get("notes") or "",
            )
        console.print(table)

    if not any_shown:
        info("No marks logged yet. Add one with `attend marks add SUBJECT`.")
    return 0
