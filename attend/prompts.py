"""Thin wrappers around Rich prompts used by interactive flows.

Centralizing these keeps the command modules readable and makes the interactive
flows easy to drive from a piped stdin during testing.
"""

from __future__ import annotations

from rich.prompt import Confirm, IntPrompt, Prompt

from . import dates
from .dates import DateParseError, TimeParseError, human, parse_date, parse_time, to_iso


def ask(message: str, default: str | None = None) -> str:
    return Prompt.ask(message, default=default if default is not None else "")


def ask_required(message: str) -> str:
    """Ask until a non-empty answer is given."""
    while True:
        value = Prompt.ask(message).strip()
        if value:
            return value
        print("  (required)")


def ask_int(message: str, default: int | None = None, min_v: int | None = None,
            max_v: int | None = None) -> int:
    while True:
        value = IntPrompt.ask(message, default=default)
        if min_v is not None and value < min_v:
            print(f"  (must be >= {min_v})")
            continue
        if max_v is not None and value > max_v:
            print(f"  (must be <= {max_v})")
            continue
        return value


def ask_yes_no(message: str, default: bool = True) -> bool:
    return Confirm.ask(message, default=default)


def ask_date(
    message: str,
    default: str | None = None,
    *,
    confirm: bool = False,
) -> str:
    """Ask for a date in any accepted format; returns an ISO (YYYY-MM-DD) string.

    Re-prompts on invalid input (never crashes). When ``confirm`` is set, echoes
    the parsed date back and asks for confirmation before accepting.
    """
    while True:
        raw = Prompt.ask(message, default=default if default is not None else "").strip()
        if not raw and default:
            raw = default
        try:
            d = parse_date(raw)
        except DateParseError as exc:
            print(f"  {exc}")
            continue
        if confirm:
            print(f"  → Parsed as: {human(d)}")
            if not Confirm.ask("    Correct?", default=True):
                continue
        return to_iso(d)


def ask_time(message: str, default: str = "23:59") -> str:
    """Ask for a time in any accepted format; returns ``HH:MM`` (24h).

    Pressing Enter accepts ``default`` (23:59 for optional due times).
    """
    while True:
        raw = Prompt.ask(message, default=default).strip()
        try:
            return parse_time(raw, default=default)
        except TimeParseError as exc:
            print(f"  {exc}")


def confirm_in_semester(d_iso: str) -> bool:
    """If a date is outside the configured semester, warn and ask to proceed.

    Returns True to proceed, False to abort. Always True when no semester is set
    or the date is in range.
    """
    from . import config  # local import to avoid import cycles

    sem = config.semester()
    if not sem:
        return True
    d = parse_date(d_iso)
    start = parse_date(sem["start"])
    end = parse_date(sem["end"])
    if start <= d <= end:
        return True
    print(
        f"  This date ({human(d)}) is outside the current semester "
        f"({sem['start']} → {sem['end']})."
    )
    return Confirm.ask("    Proceed anyway?", default=True)


def ask_choice(message: str, choices: list[str], default: str | None = None) -> str:
    return Prompt.ask(message, choices=choices, default=default)


def ask_optional(message: str) -> str:
    """Ask for an optional free-text value (may be empty)."""
    return Prompt.ask(message, default="").strip()
