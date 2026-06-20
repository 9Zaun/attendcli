"""Command-line entry point and argument parsing for AttendCLI.

The parser defines the full command surface from the PRD. Each handler imports
its implementation module lazily so the app stays runnable while later phases
are still being built.
"""

from __future__ import annotations

import argparse
import sys

from . import storage
from .console import error
from .dates import DateParseError

# Commands that are allowed to run before `attend init` has been completed.
_NO_INIT_REQUIRED = {"init", "config", "help"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="attend",
        description="Terminal-first academic survival system.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- Core daily ---
    sub.add_parser("day", help="Full daily dashboard (read-only)")

    p_log = sub.add_parser("log", help="End-of-day Y/N/C/S logging flow")
    p_log.add_argument("--date", default=None, help="Date (YYYY-MM-DD, today, yesterday)")

    p_holiday = sub.add_parser("holiday", help="Declare a full holiday for a day")
    p_holiday.add_argument("--date", default=None, help="Date (default: today)")

    # --- Attendance & bunks ---
    p_status = sub.add_parser("status", help="Per-subject bunk economy table")
    p_status.add_argument("subject", nargs="?", default=None)

    p_sim = sub.add_parser("sim", help="Simulate bunking N more classes of a subject")
    p_sim.add_argument("subject")
    p_sim.add_argument("n", type=int)

    p_hist = sub.add_parser("history", help="Chronological attendance log")
    p_hist.add_argument("subject", nargs="?", default=None)
    p_hist.add_argument("--week", type=int, default=None)

    p_bunks = sub.add_parser("bunks", help="View bunk log with reasons and notes")
    p_bunks.add_argument("--subject", default=None)

    # --- Tasks ---
    sub.add_parser("add", help="Interactive task/deadline/event creation")

    p_tasks = sub.add_parser("tasks", help="View pending items sorted by score")
    p_tasks.add_argument("--tag", default=None)
    p_tasks.add_argument("--subject", default=None)
    p_tasks.add_argument("--kind", default=None, choices=["task", "deadline", "event"])
    p_tasks.add_argument("--done", action="store_true", help="Show completed items")
    p_tasks.add_argument("--cancelled", action="store_true", help="Show cancelled items")

    p_done = sub.add_parser("done", help="Mark item complete")
    p_done.add_argument("id")

    p_cancel = sub.add_parser("cancel", help="Mark item cancelled")
    p_cancel.add_argument("id")

    p_show = sub.add_parser("show", help="Show full item detail")
    p_show.add_argument("id")

    p_crunch = sub.add_parser("crunch", help="7-day schedule board (no flags opens board)")
    p_crunch.add_argument("--undo", action="store_true", help="Revert to previous plan")
    p_crunch.add_argument("--replan", action="store_true",
                          help="Regenerate the full schedule from scratch")
    crunch_sub = p_crunch.add_subparsers(dest="crunch_command")
    p_move = crunch_sub.add_parser("move", help="Reschedule a task to a date")
    p_move.add_argument("task_id")
    p_move.add_argument("date")

    # --- Notes ---
    p_notes = sub.add_parser("notes", help="View Notebox entries")
    p_notes.add_argument("--subject", default=None)
    p_notes.add_argument("--date", default=None)
    p_notes.add_argument("--week", type=int, default=None)

    # --- Weeks ---
    p_weeks = sub.add_parser("weeks", help="Week box strip / drill into week N")
    p_weeks.add_argument("n", nargs="?", type=int, default=None)

    p_week = sub.add_parser("week", help="Set week goal / reflection")
    week_sub = p_week.add_subparsers(dest="week_command")
    p_wset = week_sub.add_parser("set", help="Set a week's goal")
    p_wset.add_argument("n", type=int)
    p_wset.add_argument("text")
    p_wreflect = week_sub.add_parser("reflect", help="Add/edit a week's reflection")
    # Accept either `reflect N "text"` or `reflect "text"` (current week). Allow
    # zero args so the command can show a friendly usage hint instead of a raw
    # argparse error when invoked with nothing.
    p_wreflect.add_argument("args", nargs="*")

    # --- Marks ---
    # `attend marks add SUBJECT` or `attend marks [SUBJECT]`. Parsed manually
    # below to avoid argparse subparser/positional ambiguity.
    p_marks = sub.add_parser("marks", help="View marks log / add a component")
    p_marks.add_argument("rest", nargs="*")

    # --- Subjects & summary ---
    sub.add_parser("subjects", help="List configured subjects (alias, code, credits, reserve)")
    sub.add_parser("summary", help="Compact one-screen semester overview")

    # --- Heatmap & export ---
    sub.add_parser("heatmap", help="Render terminal heatmap (task completion)")
    sub.add_parser("export", help="Generate full ZIP of all CSVs")

    # --- Setup & config ---
    sub.add_parser("init", help="Initialize a new semester")
    sub.add_parser("new-sem", help="Archive current semester and start a fresh one")
    sub.add_parser("reset", help="Archive and wipe all data (no re-init)")

    p_sem = sub.add_parser("sem", help="Semester editing")
    sem_sub = p_sem.add_subparsers(dest="sem_command")
    sem_sub.add_parser("edit", help="Edit semester end date")

    p_tt = sub.add_parser("timetable", help="Timetable editing")
    tt_sub = p_tt.add_subparsers(dest="timetable_command")
    tt_sub.add_parser("edit", help="Edit timetable (versioned)")

    p_ts = sub.add_parser("timeslots", help="Edit slot times only (keeps subjects)")
    ts_sub = p_ts.add_subparsers(dest="timeslots_command")
    ts_sub.add_parser("edit", help="Adjust slot start/end times without rebuilding")

    p_cfg = sub.add_parser("config", help="Config editing")
    cfg_sub = p_cfg.add_subparsers(dest="config_command")
    cfg_sub.add_parser("edit", help="Edit global config")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.command

    if cmd == "init":
        from .commands import setup
        return setup.cmd_init(args)
    if cmd == "new-sem":
        from .commands import setup
        return setup.cmd_new_sem(args)
    if cmd == "reset":
        from .commands import setup
        return setup.cmd_reset(args)
    if cmd == "sem":
        from .commands import setup
        return setup.cmd_sem(args)
    if cmd == "timetable":
        from .commands import setup
        return setup.cmd_timetable(args)
    if cmd == "timeslots":
        from .commands import setup
        return setup.cmd_timeslots(args)
    if cmd == "config":
        from .commands import setup
        return setup.cmd_config(args)
    if cmd == "holiday":
        from .commands import setup
        return setup.cmd_holiday(args)

    if cmd == "day":
        from .commands import daily
        return daily.cmd_day(args)
    if cmd == "log":
        from .commands import daily
        return daily.cmd_log(args)

    if cmd in {"status", "sim", "history", "bunks"}:
        from .commands import bunks
        return bunks.dispatch(cmd, args)

    if cmd in {"add", "tasks", "done", "cancel", "show", "crunch"}:
        from .commands import tasks_cmd
        return tasks_cmd.dispatch(cmd, args)

    if cmd == "notes":
        from .commands import notes
        return notes.cmd_notes(args)

    if cmd in {"weeks", "week"}:
        from .commands import weeks_cmd
        return weeks_cmd.dispatch(cmd, args)

    if cmd == "marks":
        from .commands import marks
        return marks.cmd_marks(args)

    if cmd == "subjects":
        from .commands import subjects as subjects_cmd
        return subjects_cmd.cmd_subjects(args)
    if cmd == "summary":
        from .commands import summary as summary_cmd
        return summary_cmd.cmd_summary(args)

    if cmd == "heatmap":
        from .commands import heatmap
        return heatmap.cmd_heatmap(args)
    if cmd == "export":
        from .commands import export
        return export.cmd_export(args)

    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command not in _NO_INIT_REQUIRED and not storage.is_initialized():
        error("No semester configured yet. Run `attend init` first.")
        return 1

    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        error("\nAborted.")
        return 130
    except DateParseError as exc:
        value = exc.value if exc.value is not None else ""
        error(
            f"Invalid date '{value}'. Use YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, "
            "today/yesterday/tomorrow, or a day name."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
