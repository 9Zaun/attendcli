"""Filesystem locations for AttendCLI data.

All data lives in a single home directory. By default this is ``~/.attendcli/``
but it can be overridden with the ``ATTENDCLI_HOME`` environment variable, which
makes the app easy to test in isolation.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "ATTENDCLI_HOME"

# Logical name -> filename. These mirror the data files described in the PRD,
# plus two operational files (schedule + daystate) the scheduler/day-handling
# need to persist their own state.
DATA_FILES = {
    "config": "config.json",
    "timetable": "timetable.json",
    "attendance": "attendance.json",
    "tasks": "tasks.json",
    "marks": "marks.json",
    "weeks": "weeks.json",
    "notebox": "notebox.json",
    "bunklog": "bunklog.json",
    "schedule": "schedule.json",
    "daystate": "daystate.json",
}


def home_dir() -> Path:
    """Return the AttendCLI data directory, creating it if needed."""
    override = os.environ.get(ENV_HOME)
    base = Path(override).expanduser() if override else Path.home() / ".attendcli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_path(name: str) -> Path:
    """Return the absolute path for a logical data file name."""
    if name not in DATA_FILES:
        raise KeyError(f"Unknown data file: {name}")
    return home_dir() / DATA_FILES[name]


def archive_base() -> Path:
    """Sibling archive directory (``<home>_archive``), created on demand.

    For the default home this is ``~/.attendcli_archive``; for a test/override
    home it sits alongside it so archives stay isolated too.
    """
    base = Path(str(home_dir()).rstrip("/\\") + "_archive")
    base.mkdir(parents=True, exist_ok=True)
    return base


def all_data_paths() -> list[Path]:
    """Existing on-disk data files in the home directory."""
    home = home_dir()
    return [home / fname for fname in DATA_FILES.values() if (home / fname).exists()]
