"""Date parsing and semester/week helpers.

All dates are stored on disk as ISO strings (``YYYY-MM-DD``). This module is the
single place that knows how to parse user input and compute week numbers.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

ISO = "%Y-%m-%d"

# Optional override for the current date, mirroring ``ATTENDCLI_HOME``: set
# ``ATTEND_TODAY=YYYY-MM-DD`` to freeze "today" for tests and reproducible runs.
ENV_TODAY = "ATTEND_TODAY"

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_FULL = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Accepted explicit date formats (tried in order).
_DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]

# Lowercased day name -> weekday index (Mon=0). Accepts full names + 3-letter.
_DAY_NAME_INDEX = {}
for _i, (_short, _full) in enumerate(zip(WEEKDAY_NAMES, WEEKDAY_FULL)):
    _DAY_NAME_INDEX[_full.lower()] = _i
    _DAY_NAME_INDEX[_short.lower()] = _i


class DateParseError(ValueError):
    """Raised when a date string can't be parsed in any accepted format.

    Carries the offending ``value`` so top-level handlers can render a friendly
    one-liner that echoes exactly what the user typed.
    """

    def __init__(self, message: str, value: str | None = None):
        super().__init__(message)
        self.value = value


class TimeParseError(ValueError):
    """Raised when a time string can't be parsed in any accepted format."""


def today() -> date:
    override = os.environ.get(ENV_TODAY)
    if override:
        try:
            return datetime.strptime(override.strip(), ISO).date()
        except ValueError:
            pass
    return date.today()


def to_iso(d: date) -> str:
    return d.strftime(ISO)


def parse_iso(s: str) -> date:
    return datetime.strptime(s, ISO).date()


def most_recent_weekday(target_idx: int, ref: date | None = None) -> date:
    """Most recent occurrence (today inclusive) of a weekday index."""
    base = ref or today()
    delta = (base.weekday() - target_idx) % 7
    return base - timedelta(days=delta)


def parse_date(s: str, *, ref: date | None = None) -> date:
    """Parse a flexible date string into a ``date``.

    Accepts ``YYYY-MM-DD``, ``DD-MM-YYYY``, ``DD/MM/YYYY``, the keywords
    ``today``/``yesterday``/``tomorrow``, and day names (``monday`` ...), which
    resolve to the most recent past occurrence (today inclusive).

    Raises ``DateParseError`` on unrecognized input.
    """
    if s is None:
        raise DateParseError("empty date", value=s)
    key = s.strip().lower()
    if key == "":
        raise DateParseError("empty date", value=s)
    base = ref or today()
    if key == "today":
        return base
    if key == "yesterday":
        return base - timedelta(days=1)
    if key == "tomorrow":
        return base + timedelta(days=1)
    if key in _DAY_NAME_INDEX:
        return most_recent_weekday(_DAY_NAME_INDEX[key], base)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise DateParseError(
        f"'{s}' is not a valid date. Use YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, "
        "today/yesterday/tomorrow, or a day name.",
        value=s,
    )


def parse_date_arg(s: str | None, *, default: date | None = None) -> date:
    """Parse a user-supplied date argument (CLI flag).

    ``None``/empty returns ``default`` (or today). Delegates to ``parse_date``
    for everything else.
    """
    if s is None or s.strip() == "":
        return default if default is not None else today()
    return parse_date(s)


def parse_time(s: str, *, default: str | None = None) -> str:
    """Parse a flexible time string and return ``HH:MM`` (24h).

    Accepts ``HH:MM`` / ``H:MM`` (24h) and ``HH:MM AM/PM`` (12h, case
    insensitive). Empty input returns ``default`` if provided, else raises.
    """
    if s is None or s.strip() == "":
        if default is not None:
            return default
        raise TimeParseError("empty time")
    raw = s.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise TimeParseError(
        f"'{s}' is not a valid time. Use HH:MM (24h) or HH:MM AM/PM."
    )


def to_12h(t: str) -> str:
    """Format a stored 24h ``HH:MM`` time as 12h with AM/PM (e.g. ``09:00 AM``).

    Falls back to the raw string if it isn't a parseable ``HH:MM`` time, so the
    display never crashes on legacy/odd data.
    """
    if not t:
        return t
    try:
        return datetime.strptime(t.strip(), "%H:%M").strftime("%I:%M %p")
    except ValueError:
        return t


_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def human(d: date) -> str:
    """Human-readable date, e.g. 'Monday, 4 August 2026'."""
    return f"{WEEKDAY_FULL[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]} {d.year}"


def weekday_short(d: date) -> str:
    return WEEKDAY_NAMES[d.weekday()]


def weekday_full(d: date) -> str:
    return WEEKDAY_FULL[d.weekday()]


def week_number(target: date, semester_start: date) -> int:
    """1-based week number of ``target`` relative to the semester start.

    Weeks are aligned to the Monday on/before the semester start so each week
    box maps cleanly to a Mon-Sun calendar block.
    """
    start_monday = semester_start - timedelta(days=semester_start.weekday())
    delta_days = (target - start_monday).days
    return delta_days // 7 + 1


def total_weeks(semester_start: date, semester_end: date) -> int:
    start_monday = semester_start - timedelta(days=semester_start.weekday())
    delta_days = (semester_end - start_monday).days
    return max(1, delta_days // 7 + 1)


def week_start_date(week_no: int, semester_start: date) -> date:
    """Monday date that begins the given 1-based week number."""
    start_monday = semester_start - timedelta(days=semester_start.weekday())
    return start_monday + timedelta(weeks=week_no - 1)


def daterange(start: date, end: date):
    """Yield each date from start to end inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)
