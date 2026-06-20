"""Daily commands: the read-only dashboard (`attend day`) and the end-of-day
logging flow (`attend log`)."""

from __future__ import annotations

from datetime import date, timedelta

from .. import (
    attendance,
    config,
    daystate,
    journals,
    prompts,
    tasks_store,
    timetable,
    weeks,
)
from ..console import console, error, info, success, warn
from ..dates import (
    parse_date_arg,
    to_12h,
    to_iso,
    total_weeks,
    week_number,
    weekday_full,
    weekday_short,
)

WIDTH = 66
BAR_MAX = 16


# --------------------------------------------------------------------------- #
# Shared day-context resolution (Saturday / Sunday / holiday)
# --------------------------------------------------------------------------- #


def _resolve_context(d: date, *, interactive: bool):
    """Return (kind, weekday_override).

    kind is one of: 'rest', 'holiday', 'work'. ``weekday_override`` is the
    weekday whose timetable should drive the day (for working Saturdays).
    """
    d_iso = to_iso(d)
    if daystate.is_holiday(d_iso):
        return "holiday", None

    wd = weekday_short(d)
    if wd == "Sun":
        return "rest", None

    if wd == "Sat":
        decision = daystate.saturday_decision(d_iso)
        if decision is None:
            if not interactive:
                # Read-only contexts can't prompt; treat as rest until decided.
                return "rest", None
            working = prompts.ask_yes_no(
                f"Is {d_iso} a working Saturday?", default=False
            )
            if not working:
                daystate.record_saturday(d_iso, False)
                return "rest", None
            follows = prompts.ask_choice(
                "Which day's timetable does it follow?",
                choices=["Mon", "Tue", "Wed", "Thu", "Fri"],
                default="Mon",
            )
            daystate.record_saturday(d_iso, True, follows)
            return "work", follows
        if not decision["working"]:
            return "rest", None
        return "work", decision.get("follows")

    return "work", None


# --------------------------------------------------------------------------- #
# attend day
# --------------------------------------------------------------------------- #


def _section(title: str) -> None:
    console.print(f"\n[bold]{title}[/bold]")
    console.print("[dim]" + "─" * len(title) + "[/dim]")


def _header(d: date) -> None:
    sem = config.semester()
    start = parse_date_arg(sem["start"])
    end = parse_date_arg(sem["end"])
    label = sem.get("label", "Semester")
    if d < start:
        top = (
            f"  {weekday_full(d)} · {d.strftime('%b %d, %Y')} · "
            f"Pre-semester (starts on {start.strftime('%b %d, %Y')}) · {label}"
        )
    else:
        wn = week_number(d, start)
        tw = total_weeks(start, end)
        top = (
            f"  {weekday_full(d)} · {d.strftime('%b %d, %Y')} · "
            f"Week {wn} of {tw} · {label}"
        )
    inner = max(WIDTH - 2, len(top) + 1)
    bar = "─" * inner
    console.print(f"[cyan]┌{bar}┐[/cyan]")
    console.print(f"[cyan]│[/cyan][bold]{top.ljust(inner)}[/bold][cyan]│[/cyan]")
    console.print(f"[cyan]└{bar}┘[/cyan]")


def _economy_inline(code: str) -> str:
    eco = attendance.economy_for(code)
    slack = eco["slack"]
    sp = eco["spendable_bunks"]
    sign = "+" if slack >= 0 else ""
    color = "red" if slack < 0 else ("yellow" if eco["spendable_bunks"] == 0 else "green")
    return f"[{color}]slack {sign}{slack}[/{color}]  spendable {sp}"


def _render_schedule(d: date, weekday_override):
    slots = timetable.slots_for_date(d, weekday_override=weekday_override)
    if not slots:
        info("  (no slots scheduled)")
        return
    for slot in slots:
        # Dashboard shows 12h AM/PM; times remain stored internally as 24h.
        t = to_12h(slot.get("time", "")) or "  :  "
        stype = slot.get("type")
        if stype == timetable.BREAK:
            console.print(f"  {t}  [dim]── break (non-loggable) ──[/dim]")
        elif stype == timetable.LUNCH:
            console.print(f"  {t}  [dim]── lunch (non-loggable) ──[/dim]")
        elif stype == timetable.TUTORIAL:
            console.print(f"  {t}  [magenta]tutorial-slot[/magenta] [dim](resolve at log)[/dim]")
        elif stype == timetable.SUBJECT:
            code = slot.get("subject", "?")
            alias = config.alias_for(code)
            console.print(f"  {t}  [bold]{alias:<6}[/bold] {_economy_inline(code)}")


def _bunk_bar(eco: dict) -> str:
    """Three-segment bar in order: spendable (green) | reserve earned (yellow) |
    not-yet-earned reserve (dim empty)."""
    sp = eco["spendable_bunks"]
    re = eco["reserve_earned"]
    em = eco["reserve_unearned"]
    if sp + re + em == 0:
        return "[dim]····[/dim]"
    cap = BAR_MAX
    # Reserve segments that actually exist must remain visible even when the
    # spendable count is large enough to fill the whole bar on its own.
    reserved = (1 if re > 0 else 0) + (1 if em > 0 else 0)
    g = min(sp, max(0, cap - reserved)); cap -= g
    y = min(re, cap); cap -= y
    d = min(em, cap)
    return f"[green]{'█' * g}[/green][yellow]{'█' * y}[/yellow][dim]{'·' * d}[/dim]"


def _render_bunk_budget():
    for s in config.subjects():
        eco = attendance.economy_for(s["code"])
        bar = _bunk_bar(eco)
        slack = eco["slack"]
        sign = "+" if slack >= 0 else ""
        label = eco["alias"]
        line = (
            f"  {label:<6} [{bar}] "
            f"spendable {eco['spendable_bunks']} · "
            f"reserve {eco['reserve_earned']}/{eco['reserve']} · "
            f"slack {sign}{slack}"
        )
        console.print(line)
        # Guardrails / warnings.
        if eco["spendable_bunks"] == 0 and not eco["below_75"]:
            warn(f"         ⚠ not safe to bunk {label} (no spendable bunks)")
        if eco["below_75"]:
            if eco["recoverable"]:
                warn(
                    f"         ⚠ below 75% — attend {eco['recovery_attends']} more "
                    f"in a row to recover"
                )
                info(
                    f"           [dim]≤ {eco['remaining_classes']} scheduled slots remain "
                    "(upper bound, excl. declared holidays; future holidays/exam "
                    "weeks not counted)[/dim]"
                )
            else:
                error(
                    f"         ✖ CANNOT recover {label} this semester — need "
                    f"{eco['recovery_attends']}, but at most {eco['remaining_classes']} "
                    "scheduled slots remain"
                )
                info(
                    "           [dim](upper-bound estimate; future holidays/exam "
                    "weeks would only lower it)[/dim]"
                )
        elif eco["at_floor"]:
            warn(f"         ⚠ {label} at the floor — any absence drops below 75%")


def _render_upcoming(d: date):
    ups = tasks_store.upcoming(7, ref_today=d)
    if not ups:
        info("  (nothing due in the next 7 days)")
        return
    id_map = tasks_store.by_id_map()
    from .. import scoring

    for it in ups:
        ref = scoring.reference_date(it, id_map)
        subj = config.alias_for(it["subject"]) if it.get("subject") else "-"
        tags = " ".join(f"#{t}" for t in it.get("tags", []))
        console.print(
            f"  [cyan]{it['id']}[/cyan] [bold]{it['title']}[/bold] "
            f"[dim]({it['kind']}, {subj}, due {ref}, p{it['priority']})[/dim] {tags}"
        )


def _render_week_goal(d: date):
    sem = config.semester()
    start = parse_date_arg(sem["start"])
    wn = week_number(d, start)
    wk = weeks.get_week(wn)
    goal = (wk or {}).get("goal", "")
    if goal:
        console.print(f"  {goal}")
    else:
        info("  (no goal set — `attend week set %d \"...\"`)" % wn)


def cmd_day(args) -> int:
    d = parse_date_arg(None)
    kind, override = _resolve_context(d, interactive=True)

    if kind in {"rest", "holiday"}:
        _header(d)
        msg = (
            "Holiday — no classes. Enjoy the day off."
            if kind == "holiday"
            else config.get_setting("rest_message")
        )
        console.print(f"\n[bold green]{msg}[/bold green]\n")
        return 0

    _header(d)

    _section("TODAY'S SCHEDULE")
    _render_schedule(d, override)

    _section("BUNK BUDGET")
    _render_bunk_budget()

    _section("UPCOMING ITEMS (next 7 days)")
    _render_upcoming(d)

    sem = config.semester()
    start = parse_date_arg(sem["start"])
    if d < start:
        _section("WEEK GOAL")
        info("  (pre-semester — week boxes start on the semester start date)")
    else:
        wn = week_number(d, start)
        _section(f"WEEK {wn} GOAL")
        _render_week_goal(d)
    console.print()
    return 0


# --------------------------------------------------------------------------- #
# attend log
# --------------------------------------------------------------------------- #


def _previous_working_day(d: date) -> date | None:
    cur = d - timedelta(days=1)
    for _ in range(7):
        wd = weekday_short(cur)
        if wd == "Sun":
            cur -= timedelta(days=1)
            continue
        if wd == "Sat":
            dec = daystate.saturday_decision(to_iso(cur))
            if dec is None or not dec["working"]:
                cur -= timedelta(days=1)
                continue
        return cur
    return None


def _log_subject(code: str, time: str, slot_no, scheduled_subject, swapped: bool):
    """Prompt Y/N/C for a concrete subject and build its event + journal calls."""
    status = prompts.ask_choice(
        f"    {config.alias_for(code)} @ {time}", choices=["Y", "N", "C"], default="Y"
    ).upper()
    reason = note = ""
    if status == attendance.PRESENT:
        note = prompts.ask_optional("      note (optional, for Notebox)")
    elif status == attendance.ABSENT:
        reason = prompts.ask_optional("      reason (e.g. project work, unwell)")
        note = prompts.ask_optional("      note (optional, for Bunk Log)")
    event = {
        "date": None,  # filled by caller
        "slot": slot_no,
        "time": time,
        "scheduled_subject": scheduled_subject,
        "subject": code,
        "status": status,
        "reason": reason,
        "note": note,
        "swapped": swapped,
        "kind": "subject",
    }
    return event


def cmd_log(args) -> int:
    d = parse_date_arg(getattr(args, "date", None))
    d_iso = to_iso(d)

    sem = config.semester()
    sem_start = parse_date_arg(sem["start"])
    sem_end = parse_date_arg(sem["end"])

    # Guard against logging outside the configured semester window. Pre-semester
    # (and post-semester) days would otherwise be logged against the wrong
    # timetable; require an explicit confirmation first.
    if d < sem_start or d > sem_end:
        where = "before the semester start" if d < sem_start else "after the semester end"
        warn(
            f"{d_iso} ({weekday_full(d)}) is {where} "
            f"({sem['start']} → {sem['end']})."
        )
        if not prompts.ask_yes_no("Log it anyway?", default=False):
            info("Log cancelled.")
            return 0

    kind, override = _resolve_context(d, interactive=True)

    if kind == "holiday":
        info(f"{d_iso} is marked as a holiday. Nothing to log.")
        return 0
    if kind == "rest":
        info(f"{d_iso} ({weekday_full(d)}) is a rest day. Nothing to log.")
        return 0

    # Reminder about an unlogged previous working day — only within the semester.
    prev = _previous_working_day(d)
    if prev and sem_start <= prev <= sem_end \
            and not attendance.has_events_for_date(to_iso(prev)) \
            and not daystate.is_holiday(to_iso(prev)):
        warn(f"Reminder: {to_iso(prev)} ({weekday_short(prev)}) is still unlogged.")

    if attendance.has_events_for_date(d_iso):
        if not prompts.ask_yes_no(
            f"You've already logged {d_iso}. Overwrite?", default=False
        ):
            info("Log cancelled.")
            return 0
        # Overwrite: clear the day's existing entries before re-running the flow.
        attendance.replace_events_for_date(d_iso, [])
        journals.remove_for_date(d_iso)

    slots = timetable.slots_for_date(d, weekday_override=override)
    loggable = [s for s in slots if timetable.is_loggable(s)]
    if not loggable:
        info("No loggable slots for this day.")
        return 0

    console.rule(f"Logging {d_iso} ({weekday_full(d)})")
    valid_codes = config.subject_codes()
    events: list[dict] = []

    for slot in loggable:
        time = slot.get("time", "")
        slot_no = slot.get("slot")
        stype = slot.get("type")

        if stype == timetable.TUTORIAL:
            info(f"  [magenta]Tutorial slot @ {time}[/magenta]")
            raw = prompts.ask(
                "    Enter subject code claimed, or -1 if cancelled", default="-1"
            ).strip()
            if raw == "-1":
                events.append({
                    "date": None, "slot": slot_no, "time": time,
                    "scheduled_subject": None, "subject": None,
                    "status": attendance.CANCELLED, "reason": "", "note": "",
                    "swapped": False, "kind": "tutorial-slot",
                })
                continue
            subj = config.find_subject(raw)
            if not subj:
                warn(f"    Unknown subject '{raw}', recording as cancelled.")
                events.append({
                    "date": None, "slot": slot_no, "time": time,
                    "scheduled_subject": None, "subject": None,
                    "status": attendance.CANCELLED, "reason": "", "note": "",
                    "swapped": False, "kind": "tutorial-slot",
                })
                continue
            ev = _log_subject(subj["code"], time, slot_no, None, swapped=False)
            ev["kind"] = "tutorial-slot"
            events.append(ev)
            continue

        # Regular subject slot — allow Y/N/C/S. Prompt shows the alias.
        code = slot.get("subject")
        choice = prompts.ask_choice(
            f"  {config.alias_for(code)} @ {time}",
            choices=["Y", "N", "C", "S"],
            default="Y",
        ).upper()

        if choice == "S":
            actual_raw = prompts.ask_required("    Which subject was actually taught?")
            actual = config.find_subject(actual_raw)
            while not actual:
                warn(f"    Unknown subject '{actual_raw}'.")
                actual_raw = prompts.ask_required("    Which subject was actually taught?")
                actual = config.find_subject(actual_raw)
            ev = _log_subject(actual["code"], time, slot_no, code, swapped=True)
            events.append(ev)
            continue

        reason = note = ""
        if choice == attendance.PRESENT:
            note = prompts.ask_optional("      note (optional, for Notebox)")
        elif choice == attendance.ABSENT:
            reason = prompts.ask_optional("      reason (e.g. project work, unwell)")
            note = prompts.ask_optional("      note (optional, for Bunk Log)")
        events.append({
            "date": None, "slot": slot_no, "time": time,
            "scheduled_subject": code, "subject": code,
            "status": choice, "reason": reason, "note": note,
            "swapped": False, "kind": "subject",
        })

    for ev in events:
        ev["date"] = d_iso

    # Snapshot economy before/after for the summary.
    prior_events = [e for e in attendance.events() if e.get("date") != d_iso]
    after_events = prior_events + events

    attendance.replace_events_for_date(d_iso, events)
    journals.remove_for_date(d_iso)
    for ev in events:
        if ev["subject"] and ev["status"] == attendance.PRESENT and ev["note"]:
            journals.add_note(d_iso, ev["time"], ev["subject"], ev["note"])
        if ev["subject"] and ev["status"] == attendance.ABSENT and (ev["reason"] or ev["note"]):
            journals.add_bunk(d_iso, ev["time"], ev["subject"], ev["reason"], ev["note"])

    _print_summary(prior_events, after_events, events)
    return 0


def _print_summary(prior_events, after_events, todays_events):
    console.rule("Summary")
    # Subjects touched today (those with Y/N events).
    touched = []
    for code in config.subject_codes():
        if any(e.get("subject", "").lower() == code.lower() for e in todays_events
               if e.get("subject")):
            touched.append(code)

    cancelled_only = [
        e for e in todays_events
        if e.get("status") == attendance.CANCELLED
    ]

    for code in touched:
        before = attendance.economy_from(prior_events, code)
        after = attendance.economy_from(after_events, code)
        # Did this subject only get cancellations today?
        had_effect = any(
            e.get("subject", "").lower() == code.lower()
            and e.get("status") in (attendance.PRESENT, attendance.ABSENT)
            for e in todays_events if e.get("subject")
        )
        label = config.alias_for(code)
        if not had_effect:
            console.print(f"  {label:<6} [dim][C] no change[/dim]")
            continue
        reserve_note = ""
        if after["spendable_bunks"] < before["spendable_bunks"] and after["reserve"] > 0 \
                and after["safe_bunks"] <= after["reserve"]:
            reserve_note = "  [yellow]⚠ reserve in use[/yellow]"
        tick_note = ""
        if not reserve_note and after["slack"] != before["slack"] \
                and after["safe_bunks"] == before["safe_bunks"] and after["slack"] >= 0:
            next_tick = (after["safe_bunks"] + 1) * 3
            tick_note = f"  [dim](next tick at slack={next_tick})[/dim]"
        console.print(
            f"  {label:<6} slack: {before['slack']} → {after['slack']}   "
            f"safe bunks: {before['safe_bunks']} → {after['safe_bunks']}{reserve_note}{tick_note}"
        )

    if cancelled_only and not touched:
        info("  All slots cancelled — no attendance change.")
    success("Logged.")
