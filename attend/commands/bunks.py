"""Attendance & bunk commands: status, sim, history, bunks."""

from __future__ import annotations

from datetime import timedelta

from rich.table import Table

from .. import attendance, config, journals
from ..console import console, error, info, warn
from ..dates import parse_date_arg, parse_iso, to_iso, week_start_date


def dispatch(cmd: str, args) -> int:
    if cmd == "status":
        return cmd_status(args)
    if cmd == "sim":
        return cmd_sim(args)
    if cmd == "history":
        return cmd_history(args)
    if cmd == "bunks":
        return cmd_bunks(args)
    return 1


# --------------------------------------------------------------------------- #
# attend status
# --------------------------------------------------------------------------- #


def _status_row(eco: dict) -> list[str]:
    slack = eco["slack"]
    sign = "+" if slack >= 0 else ""
    if eco["below_75"]:
        flag = "[red]BELOW 75%[/red]"
    elif eco["spendable_bunks"] == 0:
        flag = "[yellow]no bunks[/yellow]"
    else:
        flag = "[green]ok[/green]"
    return [
        eco["alias"],
        str(eco["P"]),
        str(eco["A"]),
        str(eco["C"]),
        f"{sign}{slack}",
        str(eco["safe_bunks"]),
        f"{eco['reserve_earned']}/{eco['reserve']}",
        str(eco["spendable_bunks"]),
        flag,
    ]


def cmd_status(args) -> int:
    subject = getattr(args, "subject", None)
    if subject and not config.find_subject(subject):
        error(f"Unknown subject: {subject}")
        return 1

    table = Table(title="Bunk Economy", header_style="bold")
    for col in ["Subject", "P", "A", "C", "slack", "safe", "reserve", "spendable", "status"]:
        table.add_column(col)

    ecos = (
        [attendance.economy_for(config.resolve_code(subject))]
        if subject
        else attendance.all_economy()
    )
    for eco in ecos:
        table.add_row(*_status_row(eco))
    console.print(table)

    # Detailed guardrail messages below the table.
    for eco in ecos:
        if eco["below_75"]:
            if eco["recoverable"]:
                warn(
                    f"{eco['alias']}: below 75%. Attend {eco['recovery_attends']} more "
                    f"in a row to recover."
                )
                info(
                    f"  [dim]≤ {eco['remaining_classes']} scheduled slots remain "
                    "(upper bound, excl. declared holidays; future holidays/exam "
                    "weeks not counted).[/dim]"
                )
            else:
                error(
                    f"{eco['alias']}: CANNOT recover this semester — need "
                    f"{eco['recovery_attends']}, but at most {eco['remaining_classes']} "
                    "scheduled slots remain (upper-bound estimate)."
                )
        elif eco["at_floor"]:
            warn(f"{eco['alias']}: at the floor — any absence drops below 75%.")
    return 0


# --------------------------------------------------------------------------- #
# attend sim
# --------------------------------------------------------------------------- #


def cmd_sim(args) -> int:
    subject = config.find_subject(args.subject)
    if not subject:
        error(f"Unknown subject: {args.subject}")
        return 1
    n = args.n
    if n < 0:
        error("N must be >= 0.")
        return 1

    eco = attendance.economy_for(subject["code"])
    label = config.alias_for(subject["code"])
    new_slack = eco["slack"] - 3 * n
    new_safe = attendance.safe_bunks_from(new_slack)
    new_buckets = attendance.split_buckets(new_safe, eco["reserve"])
    new_spendable = new_buckets["spendable_bunks"]

    info(f"[bold]Simulating {n} more bunk(s) of {label}[/bold]")
    info(f"  slack:      {eco['slack']:+d} → {new_slack:+d}")
    info(f"  safe bunks: {eco['safe_bunks']} → {new_safe}")
    info(f"  spendable:  {eco['spendable_bunks']} → {new_spendable}")
    info(
        f"  reserve:    {eco['reserve_earned']}/{eco['reserve']} → "
        f"{new_buckets['reserve_earned']}/{eco['reserve']}"
    )

    if new_slack < 0:
        need = attendance.recovery_attends(new_slack)
        remaining = eco["remaining_classes"]
        if n == 0:
            # Nothing is being simulated; the subject is already in this state.
            if need <= remaining:
                warn(
                    f"  ⚠ {label} is already below 75% "
                    f"(need {need} consecutive attends, {remaining} classes left). "
                    "No change from simulating 0 bunks."
                )
            else:
                error(
                    f"  ✖ {label} is already unrecoverable "
                    f"(need {need}, only {remaining} classes left). "
                    "No change from simulating 0 bunks."
                )
        elif need <= remaining:
            warn(
                f"  ⚠ That drops {label} below 75%. "
                f"You'd need {need} consecutive attends to recover."
            )
        else:
            error(
                f"  ✖ That makes {label} unrecoverable this semester "
                f"(need {need}, only {remaining} classes left)."
            )
    elif new_slack == 0:
        warn(f"  ⚠ That puts {label} exactly at the floor.")
    else:
        info(f"  Still safe ({new_spendable} spendable bunk(s) remaining).")
    return 0


# --------------------------------------------------------------------------- #
# attend history
# --------------------------------------------------------------------------- #


def cmd_history(args) -> int:
    subject = getattr(args, "subject", None)
    week = getattr(args, "week", None)
    if subject and not config.find_subject(subject):
        error(f"Unknown subject: {subject}")
        return 1

    evs = attendance.events()

    if week is not None:
        sem = config.semester()
        start = week_start_date(week, parse_iso(sem["start"]))
        end = start + timedelta(days=6)
        evs = [
            e for e in evs
            if start <= parse_iso(e["date"]) <= end
        ]

    if subject:
        code = config.resolve_code(subject)
        evs = [e for e in evs if (e.get("subject") or "").lower() == code.lower()]

    evs = sorted(evs, key=lambda e: (e["date"], e.get("time") or ""))
    if not evs:
        info("No matching attendance events.")
        return 0

    table = Table(title="Attendance History", header_style="bold")
    for col in ["Date", "Time", "Subject", "Status", "Reason", "Note", "Swap"]:
        table.add_column(col)

    status_style = {"Y": "green", "N": "red", "C": "dim"}
    for e in evs:
        st = e.get("status", "")
        style = status_style.get(st, "")
        swap = ""
        if e.get("swapped"):
            swap = f"from {config.alias_for(e.get('scheduled_subject'))}"
        table.add_row(
            e["date"],
            e.get("time") or "",
            config.alias_for(e.get("subject")) if e.get("subject") else "—",
            f"[{style}]{st}[/{style}]" if style else st,
            e.get("reason") or "",
            e.get("note") or "",
            swap,
        )
    console.print(table)
    return 0


# --------------------------------------------------------------------------- #
# attend bunks
# --------------------------------------------------------------------------- #


def cmd_bunks(args) -> int:
    subject = getattr(args, "subject", None)
    if subject and not config.find_subject(subject):
        error(f"Unknown subject: {subject}")
        return 1
    entries = journals.bunks(config.resolve_code(subject) if subject else None)
    entries = sorted(entries, key=lambda b: (b["date"], b.get("time") or ""))
    if not entries:
        info("No bunk log entries.")
        return 0

    table = Table(title="Bunk Log", header_style="bold")
    for col in ["Date", "Time", "Subject", "Reason", "Note"]:
        table.add_column(col)
    for b in entries:
        table.add_row(
            b["date"], b.get("time") or "", config.alias_for(b["subject"]),
            b.get("reason") or "", b.get("note") or "",
        )
    console.print(table)
    return 0
