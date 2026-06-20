"""Setup & configuration commands: init, sem edit, timetable edit, config edit,
holiday."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .. import attendance, config, daystate, paths, storage, timetable, weeks
from ..console import console, error, info, success, warn
from ..dates import parse_date_arg, to_iso, weekday_short
from .. import prompts

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


# --------------------------------------------------------------------------- #
# attend init
# --------------------------------------------------------------------------- #


def _collect_time_structure() -> list[dict]:
    info("\n[bold]Time structure[/bold] — the fixed daily slot skeleton.")
    info("Enter slot times. Blank start time finishes the list.")
    slots: list[dict] = []
    idx = 1
    while True:
        raw = prompts.ask_optional(f"  Slot {idx} start time (e.g. 09:00)")
        if not raw:
            if slots:
                break
            warn("  At least one slot is required.")
            continue
        try:
            start = prompts.parse_time(raw)
        except prompts.TimeParseError as exc:
            warn(f"  {exc}")
            continue
        end = prompts.ask_time("    end time (e.g. 10:00)", default=start)
        slots.append({"slot": idx, "start": start, "end": end})
        idx += 1
    return slots


def _collect_subjects() -> list[dict]:
    info("\n[bold]Subjects[/bold] — blank code to finish.")
    subjects: list[dict] = []
    while True:
        code = prompts.ask_optional("  Subject code (e.g. 23CSE203)")
        if not code:
            if subjects:
                break
            warn("  At least one subject is required.")
            continue
        if any(s["code"].lower() == code.lower() for s in subjects):
            warn("  That code already exists.")
            continue
        name = prompts.ask_required("    Full name")
        alias = prompts.ask_required("    Short alias for this subject (e.g. DSA, DBMS)")
        if any((s.get("alias") or "").lower() == alias.lower() for s in subjects):
            warn("  That alias already exists; pick a unique one.")
            continue
        credits = prompts.ask_int("    Credits", default=3, min_v=0)
        reserve = prompts.ask_int("    Reserve bunks", default=0, min_v=0)
        subjects.append(
            {
                "code": code,
                "name": name,
                "alias": alias,
                "credits": credits,
                "reserve": reserve,
            }
        )
    return subjects


def _slot_type_from_input(raw: str, subjects: list[dict]) -> dict | None:
    key = raw.strip().lower()
    if key in {"break", "b"}:
        return {"type": timetable.BREAK}
    if key in {"lunch", "l"}:
        return {"type": timetable.LUNCH}
    if key in {"tutorial", "tut", "t"}:
        return {"type": timetable.TUTORIAL}
    for s in subjects:
        if s["code"].lower() == key or (s.get("alias", "").lower() == key):
            return {"type": timetable.SUBJECT, "subject": s["code"]}
    return None


def _collect_timetable(time_structure: list[dict], subjects: list[dict]) -> dict:
    info("\n[bold]Timetable[/bold] — assign each slot Monday-Friday.")
    info(
        "For each slot enter a subject alias/code, or one of: "
        "[cyan]tut[/cyan] (tutorial), [cyan]break[/cyan], [cyan]lunch[/cyan]."
    )
    info(f"Subjects: {', '.join(s.get('alias') or s['code'] for s in subjects)}")
    days: dict[str, list[dict]] = {}
    for wd in WEEKDAYS:
        info(f"\n[bold cyan]{wd}[/bold cyan]")
        day_slots: list[dict] = []
        for ts in time_structure:
            label = f"  {ts['start']}-{ts['end']}"
            while True:
                raw = prompts.ask(label, default="break")
                parsed = _slot_type_from_input(raw, subjects)
                if parsed is None:
                    warn("    Unknown entry. Use a subject alias/code, tut, break, or lunch.")
                    continue
                entry = {"slot": ts["slot"], "time": ts["start"]}
                entry.update(parsed)
                day_slots.append(entry)
                break
        days[wd] = day_slots
    return days


def cmd_init(args) -> int:
    if storage.is_initialized():
        error(
            "A semester is already initialized. Run 'attend new-sem' to start a "
            "new semester or 'attend reset' to wipe all data."
        )
        return 1

    console.rule("AttendCLI — Semester Initialization")

    time_structure = _collect_time_structure()

    info("\n[bold]Semester dates[/bold]")
    label = prompts.ask("  Semester label", default="Semester")
    start = prompts.ask_date("  Semester start date (e.g. 04-08-2026)", confirm=True)
    end = prompts.ask_date("  Tentative end date (e.g. 20-12-2026)", confirm=True)

    subjects = _collect_subjects()

    days = _collect_timetable(time_structure, subjects)

    cfg = config.load()
    cfg["semester"] = {"label": label, "start": start, "end": end}
    cfg["time_structure"] = time_structure
    cfg["subjects"] = subjects
    cfg.setdefault("settings", {})
    config.save(cfg)

    # First timetable version effective from semester start so historical
    # reconstruction works from day one.
    tt = storage.default_for("timetable")
    tt["versions"] = [{"effective_from": start, "days": days}]
    timetable.save(tt)

    weeks.regenerate()

    console.rule()
    success("Semester initialized.")
    info(f"  {label}: {start} -> {end}")
    info(f"  {len(subjects)} subjects, {len(time_structure)} daily slots.")
    info("Run [bold]attend day[/bold] to see today's dashboard.")
    return 0


# --------------------------------------------------------------------------- #
# attend new-sem / attend reset
# --------------------------------------------------------------------------- #


def _archive_current(start_label: str) -> Path:
    """Export then move all current data files into the archive folder."""
    from .export import write_zip

    archive_dir = paths.archive_base() / f"sem_{start_label}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Full export ZIP into the archive (audit copy).
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    write_zip(archive_dir / f"export_{stamp}.zip")

    # Move the raw JSON data files in.
    for p in paths.all_data_paths():
        shutil.move(str(p), str(archive_dir / p.name))
    return archive_dir


def cmd_new_sem(args) -> int:
    if not storage.is_initialized():
        error("No semester to archive. Run 'attend init' to set one up first.")
        return 1
    start_label = config.semester().get("start", "unknown")

    warn(
        f"This will archive Sem {start_label} and start a fresh semester. "
        "All current data will be moved to archive."
    )
    if not prompts.ask_yes_no("Continue?", default=False):
        info("Cancelled. Nothing was changed.")
        return 0

    archive_dir = _archive_current(start_label)
    success(f"Archived previous semester to {archive_dir}")
    info("Starting a fresh semester...\n")
    return cmd_init(args)


def cmd_reset(args) -> int:
    if not storage.is_initialized():
        error("Nothing to reset — no semester is initialized.")
        return 1
    start_label = config.semester().get("start", "unknown")

    warn(
        f"This will archive Sem {start_label} and WIPE all current data "
        "(no re-init afterwards)."
    )
    if not prompts.ask_yes_no("Continue?", default=False):
        info("Cancelled. Nothing was changed.")
        return 0

    archive_dir = _archive_current(start_label)
    success(f"Archived and wiped. Data saved to {archive_dir}")
    info("Run 'attend init' when you're ready to start a new semester.")
    return 0


# --------------------------------------------------------------------------- #
# attend sem edit
# --------------------------------------------------------------------------- #


def cmd_sem(args) -> int:
    if getattr(args, "sem_command", None) != "edit":
        info("Usage: attend sem edit")
        return 1
    cfg = config.load()
    sem = cfg.get("semester", {})
    info(f"Current end date: {sem.get('end')}")
    new_end = prompts.ask_date(
        "New end date (e.g. 20-12-2026)", default=sem.get("end"), confirm=True
    )
    sem["end"] = new_end
    cfg["semester"] = sem
    config.save(cfg)
    weeks.regenerate()
    success(f"Semester end date updated to {new_end}. Week boxes regenerated.")
    return 0


# --------------------------------------------------------------------------- #
# attend timetable edit
# --------------------------------------------------------------------------- #


def _editor_command() -> str:
    return (
        config.get_setting("editor")
        or os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
        or "vi"
    )


def cmd_timetable(args) -> int:
    if getattr(args, "timetable_command", None) != "edit":
        info("Usage: attend timetable edit")
        return 1

    today_iso = to_iso(parse_date_arg(None))
    current = timetable.version_for(parse_date_arg(None))
    days = current.get("days", {}) if current else {}

    payload = {
        "_help": (
            "Edit the Mon-Sat slot map below. Each slot is an object with 'type' "
            "(subject/tutorial-slot/break/lunch) and, for subjects, a 'subject' "
            "code. Saving creates a new version effective from today."
        ),
        "days": days,
    }

    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="attend-timetable-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        editor = _editor_command()
        try:
            subprocess.call([*editor.split(), tmp])
        except FileNotFoundError:
            error(f"Editor not found: {editor}")
            return 1
        with open(tmp, "r", encoding="utf-8") as fh:
            try:
                edited = json.load(fh)
            except json.JSONDecodeError as exc:
                error(f"Invalid JSON, not saving: {exc}")
                return 1
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    new_days = edited.get("days", {})
    if not new_days:
        warn("No days found in edited file. Aborting.")
        return 1

    timetable.add_version(new_days, today_iso)
    success(f"Timetable updated. New version effective from {today_iso}.")
    return 0


# --------------------------------------------------------------------------- #
# attend timeslots edit
# --------------------------------------------------------------------------- #


def cmd_timeslots(args) -> int:
    """Edit only the slot time structure, keeping subject assignments intact.

    Adjusting start/end times here does not rebuild the timetable: it updates
    the saved time structure and writes a new timetable version (effective
    today) that carries the same per-slot subjects but with shifted times. Older
    versions keep their stored times, so historical attendance is unaffected.
    """
    if getattr(args, "timeslots_command", None) != "edit":
        info("Usage: attend timeslots edit")
        return 1

    cfg = config.load()
    structure = cfg.get("time_structure", [])
    if not structure:
        error("No time structure configured. Run `attend init` first.")
        return 1

    info("\n[bold]Current time slots[/bold]")
    for ts in structure:
        info(f"  Slot {ts['slot']}: {ts['start']}–{ts.get('end', ts['start'])}")

    info("\nEnter new times (press Enter to keep the current value).")
    new_structure: list[dict] = []
    changed = False
    for ts in structure:
        start = prompts.ask_time(f"  Slot {ts['slot']} start", default=ts["start"])
        end = prompts.ask_time(
            f"  Slot {ts['slot']} end", default=ts.get("end", start)
        )
        if start != ts["start"] or end != ts.get("end"):
            changed = True
        new_structure.append({"slot": ts["slot"], "start": start, "end": end})

    if not changed:
        info("No changes made.")
        return 0

    cfg["time_structure"] = new_structure
    config.save(cfg)

    # Propagate the new start times into a fresh timetable version (effective
    # today) without touching the subject assignments.
    start_by_slot = {ts["slot"]: ts["start"] for ts in new_structure}
    today_iso = to_iso(parse_date_arg(None))
    current = timetable.version_for(parse_date_arg(None))
    days = current.get("days", {}) if current else {}
    new_days: dict[str, list[dict]] = {}
    for wd, slots in days.items():
        rebuilt = []
        for slot in slots:
            s = dict(slot)
            if s.get("slot") in start_by_slot:
                s["time"] = start_by_slot[s["slot"]]
            rebuilt.append(s)
        new_days[wd] = rebuilt

    if new_days:
        timetable.add_version(new_days, today_iso)
        success(
            f"Time slots updated. New timetable version effective from {today_iso} "
            "(subjects unchanged; older days keep their stored times)."
        )
    else:
        success("Time slots updated.")
    return 0


# --------------------------------------------------------------------------- #
# attend config edit
# --------------------------------------------------------------------------- #


def cmd_config(args) -> int:
    cfg = config.load()
    # Present an editable view: settings + per-subject reserve.
    payload = {
        "_help": (
            "Edit global settings and per-subject reserve bunks. Recognized "
            "settings include rest_message, editor, urgency_decay, urgency_cap, "
            "no_due_default_days, crunch_capacity_mode, crunch_daily_capacity, "
            "crunch_skip_weekends."
        ),
        "settings": {**config.DEFAULT_SETTINGS, **cfg.get("settings", {})},
        "subjects_reserve": {s["code"]: s.get("reserve", 0) for s in cfg.get("subjects", [])},
        "rest_message": cfg.get("settings", {}).get(
            "rest_message", config.DEFAULT_SETTINGS["rest_message"]
        ),
    }

    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="attend-config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        editor = _editor_command()
        try:
            subprocess.call([*editor.split(), tmp])
        except FileNotFoundError:
            error(f"Editor not found: {editor}")
            return 1
        with open(tmp, "r", encoding="utf-8") as fh:
            try:
                edited = json.load(fh)
            except json.JSONDecodeError as exc:
                error(f"Invalid JSON, not saving: {exc}")
                return 1
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    cfg["settings"] = edited.get("settings", cfg.get("settings", {}))
    # Apply reserve overrides back onto subjects.
    reserves = edited.get("subjects_reserve", {})
    for s in cfg.get("subjects", []):
        if s["code"] in reserves:
            s["reserve"] = int(reserves[s["code"]])
    config.save(cfg)
    success("Config updated.")
    return 0


# --------------------------------------------------------------------------- #
# attend holiday
# --------------------------------------------------------------------------- #


def cmd_holiday(args) -> int:
    d = parse_date_arg(getattr(args, "date", None))
    d_iso = to_iso(d)
    wd = weekday_short(d)

    # Guard: refuse to declare holidays outside the configured semester window.
    sem = config.semester()
    if sem:
        start = parse_date_arg(sem["start"])
        end = parse_date_arg(sem["end"])
        if d < start or d > end:
            where = "before the semester start" if d < start else "after the semester end"
            warn(
                f"{d_iso} ({wd}) is {where} ({sem['start']} → {sem['end']})."
            )
            if not prompts.ask_yes_no("Declare a holiday anyway?", default=False):
                info("Holiday declaration cancelled.")
                return 0

    # Resolve the slots that would have run, and record them all as cancelled.
    slots = timetable.slots_for_date(d)
    new_events = []
    for slot in slots:
        if not timetable.is_loggable(slot):
            continue
        new_events.append(
            {
                "date": d_iso,
                "slot": slot.get("slot"),
                "time": slot.get("time"),
                "scheduled_subject": slot.get("subject"),
                "subject": slot.get("subject") if slot.get("type") == timetable.SUBJECT else None,
                "status": attendance.CANCELLED,
                "reason": "",
                "note": "",
                "swapped": False,
                "kind": "holiday",
            }
        )

    # No loggable slots → nothing to cancel (rest day or all breaks/lunch).
    if not new_events:
        info(
            f"{d_iso} ({wd}) is a rest day; no attendance slots exist. "
            "No action taken."
        )
        return 0

    # Guard: don't silently overwrite a day that already has real attendance.
    existing = [e for e in attendance.events() if e.get("date") == d_iso]
    logged = [
        e for e in existing
        if e.get("status") in (attendance.PRESENT, attendance.ABSENT)
    ]
    if logged:
        warn(
            f"{d_iso} already has {len(logged)} logged event(s). "
            "Declaring a holiday will overwrite them."
        )
        if not prompts.ask_yes_no("Continue?", default=False):
            info("Holiday declaration cancelled.")
            return 0

    attendance.replace_events_for_date(d_iso, new_events)
    daystate.mark_holiday(d_iso)
    success(f"{d_iso} ({wd}) declared a holiday. {len(new_events)} slot(s) marked cancelled.")
    return 0
