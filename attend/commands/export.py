"""Full data export: `attend export` -> one ZIP of per-category CSVs."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from pathlib import Path

from .. import attendance, config, journals, paths, storage, tasks_store, timetable, weeks
from ..commands.heatmap import completion_counts
from ..console import success


def _csv(rows: list[list], header: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _attendance_summary() -> str:
    rows = []
    for eco in attendance.all_economy():
        rows.append([
            eco["code"], eco.get("alias", eco["code"]), eco["P"], eco["A"], eco["C"],
            eco["slack"], eco["safe_bunks"], eco["spendable_bunks"],
            eco["reserve"], eco["reserve_earned"],
        ])
    return _csv(rows, ["subject", "alias", "P", "A", "C", "slack", "safe_bunks",
                       "spendable_bunks", "reserve", "reserve_earned"])


def _attendance_log() -> str:
    rows = []
    for e in sorted(attendance.events(), key=lambda x: (x["date"], x.get("time") or "")):
        rows.append([
            e["date"], e.get("time") or "", e.get("subject") or "",
            e.get("status") or "", e.get("reason") or "", e.get("note") or "",
            e.get("scheduled_subject") or "", "yes" if e.get("swapped") else "",
            e.get("kind") or "",
        ])
    return _csv(rows, ["date", "time", "subject", "status", "reason", "note",
                       "scheduled_subject", "swapped", "kind"])


def _tasks() -> str:
    rows = []
    for it in tasks_store.items():
        rows.append([
            it["id"], it["kind"], it.get("subject") or "", it["title"],
            it.get("due") or "", it.get("event_time") or "", it.get("linked_to") or "",
            it["priority"], ";".join(it.get("tags", [])), it["status"],
            it.get("notes") or "", it.get("created_at") or "",
            it.get("completed_at") or "",
        ])
    return _csv(rows, ["id", "kind", "subject", "title", "due", "event_time",
                       "linked_to", "priority", "tags", "status", "notes",
                       "created_at", "completed_at"])


def _marks() -> str:
    rows = []
    for e in storage.load("marks").get("entries", []):
        rows.append([
            e["subject"], e["component"], e["score"],
            e.get("weightage") or "", e.get("notes") or "",
        ])
    return _csv(rows, ["subject", "component", "score", "weightage", "notes"])


def _weeks() -> str:
    rows = []
    for w in weeks.all_weeks():
        rows.append([
            w["week_number"], w["start_date"], w.get("goal") or "",
            w.get("reflection") or "",
        ])
    return _csv(rows, ["week_number", "start_date", "goal", "reflection"])


def _notebox() -> str:
    rows = [[n["date"], n.get("time") or "", n["subject"], n.get("note") or ""]
            for n in journals.notes()]
    return _csv(rows, ["date", "time", "subject", "note"])


def _bunklog() -> str:
    rows = [[b["date"], b.get("time") or "", b["subject"],
             b.get("reason") or "", b.get("note") or ""]
            for b in journals.bunks()]
    return _csv(rows, ["date", "time", "subject", "reason", "note"])


def _heatmap() -> str:
    counts = completion_counts()
    rows = [[d, counts[d]] for d in sorted(counts.keys())]
    return _csv(rows, ["date", "tasks_completed"])


def _timetable_history() -> str:
    rows = []
    for v in timetable.load().get("versions", []):
        eff = v["effective_from"]
        for day, slots in v.get("days", {}).items():
            for slot in slots:
                rows.append([
                    eff, day, slot.get("slot") or "", slot.get("time") or "",
                    slot.get("type") or "", slot.get("subject") or "",
                ])
    return _csv(rows, ["effective_from", "day", "slot", "time", "type", "subject"])


def build_csvs() -> dict[str, str]:
    """Return a mapping of CSV filename -> content for the full export."""
    return {
        "attendance_summary.csv": _attendance_summary(),
        "attendance_log.csv": _attendance_log(),
        "tasks.csv": _tasks(),
        "marks.csv": _marks(),
        "weeks.csv": _weeks(),
        "notebox.csv": _notebox(),
        "bunklog.csv": _bunklog(),
        "heatmap.csv": _heatmap(),
        "timetable_history.csv": _timetable_history(),
    }


def write_zip(out_path: Path, files: dict[str, str] | None = None) -> Path:
    """Write the full export ZIP to ``out_path`` and return it.

    ``files`` may be supplied to reuse an already-built CSV mapping (avoids
    rebuilding the data twice); otherwise it is built here.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if files is None:
        files = build_csvs()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return out_path


def cmd_export(args) -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = build_csvs()
    # Save into the data home (predictable location) rather than the shell's
    # current directory, which may be read-only or unexpected.
    out_path = write_zip(paths.home_dir() / f"attendcli_export_{stamp}.zip", files)
    success(f"Exported {len(files)} CSVs to {out_path}")
    return 0
