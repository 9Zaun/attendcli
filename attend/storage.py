"""JSON persistence layer.

Every data file is plain, human-readable JSON. Writes are atomic (write to a
temp file, then replace) so an interrupted run can never corrupt a store.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from .paths import data_path

# Default empty shapes for each store so callers never have to special-case a
# missing file. The first run of any command sees a valid (empty) structure.
_DEFAULTS: dict[str, Any] = {
    "config": {},
    "timetable": {"versions": []},
    "attendance": {"events": []},
    "tasks": {"items": [], "next_id": 1},
    "marks": {"entries": []},
    "weeks": {"weeks": []},
    "notebox": {"notes": []},
    "bunklog": {"entries": []},
    "schedule": {"current": None, "previous": None, "stale": False},
    "daystate": {"days": {}},
}


def default_for(name: str) -> Any:
    """Return a fresh copy of the default structure for a store."""
    return json.loads(json.dumps(_DEFAULTS.get(name, {})))


def load(name: str) -> Any:
    """Load a data store by logical name, returning its default if absent."""
    path = data_path(name)
    if not path.exists():
        return default_for(name)
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        # A corrupt/empty file should not crash the whole app; fall back to
        # the default shape. The original file is left untouched for inspection.
        return default_for(name)


def save(name: str, data: Any) -> None:
    """Atomically write a data store to disk as pretty-printed JSON."""
    path = data_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def is_initialized() -> bool:
    """True once a semester has been configured via ``attend init``."""
    cfg = load("config")
    return bool(cfg.get("semester"))
