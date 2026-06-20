# AttendCLI

Terminal-first, locally-run academic survival system. Tracks attendance and the
bunk economy (derived from the 75% rule), tasks/deadlines/events with a
priority×urgency scheduler, week boxes, marks, and a productivity heatmap.

All data lives on disk as plain JSON in `~/.attendcli/` (override with the
`ATTENDCLI_HOME` environment variable). No cloud, no GUI, no web server.

See [`AttendCLI_PRD.md`](AttendCLI_PRD.md) for the original specification.
This README reflects **what the CLI does today** — where the code and PRD
differ, the code wins.

## Install

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This exposes the `attend` command (entry point: `attend.cli:main`). You can
also run `python -m attend`.

## Quick start

```bash
attend init        # one-time semester setup (time slots, subjects, timetable)
attend day         # morning dashboard (read-only)
attend log         # end-of-day Y/N/C/S logging
```

## Scoring model

Tasks, deadlines, and events share one ranking key used by `attend tasks` and
the crunch scheduler:

- **Priority** is `1–5` (`5` = most important / most effortful). There is **no
  separate effort field** — priority embeds effort.
- **Reference date** drives urgency: deadlines use `due`; events use the date
  portion of `event_time`; linked tasks inherit their linked item's date (the
  link wins over any `due` on the task itself); unlinked tasks fall back to
  their own optional `due`.
- **Urgency** `u = exp(D / d)` where `d` = days until the reference date
  (minimum `0.5`), `D` = decay constant (`urgency_decay`, default `7`). `u` is
  capped at `urgency_cap` (default `100`) so very near deadlines don't blow up.
- **Score** `= priority × u`. Items without a reference date use
  `no_due_default_days` (default `30`) as `d`, so they sort mostly by priority.

## Subjects & aliases

Each subject has a full code (e.g. `23CSE203`), a display name, a short alias
(e.g. `OS`), credits, and a reserve-bunk target. Every command that accepts a
subject takes **either** the alias or the full code (case-insensitive). Aliases
are shown by default in dashboards and tables.

`attend subjects` lists all subjects in a table (alias, code, name, credits,
reserve target).

## Bunk economy

Per subject, from logged `Y`/`N`/`C` events:

- `slack = P − 3·A`
- `safe_bunks = max(0, ⌊slack/3⌋)`

Negative slack is supported. The CLI warns when you are below 75%, at the floor
(`slack == 0`), or mathematically unable to recover given remaining scheduled
classes (an upper-bound estimate excluding future unknown holidays).

**Reserve bunks are earned, not pre-allocated.** They start at 0 and fill first:
the first `reserve` earned bunks go into the reserve bucket; anything beyond is
spendable. Bunking spends from spendable first. The per-subject bar on
`attend day` has three segments in order:
`[spendable █ | reserve earned █ | not-yet-earned ·]`.

`attend status`, `attend sim SUBJECT N`, and `attend history` expose the same
math. `attend bunks` shows the bunk log (reasons and notes from `N` slots).

## Crunch scheduler

`attend crunch` opens an interactive 7-day Kanban board:

- Optional **OVERDUE** column when pending tasks have reference dates before
  today.
- Seven day columns starting at the current window (today by default); the
  current calendar day is highlighted **TODAY**.
- A second row shows non-movable **deadline** (`◆`) and **event** (`★`) markers
  on their reference dates.
- Tasks that cannot fit before their deadline appear in **⚠ UNSCHEDULABLE**.
- Days above the configured daily capacity show a **⚠ load/capacity** warning;
  a separate **ABOVE CAPACITY** section explains deadline-driven overload.

Navigate with `→`/`l` (next 7 days), `←`/`h` (previous 7 days), `q` to quit.
Over SSH with a TTY this is fully interactive; piped or non-TTY usage renders
the board once and exits.

The underlying planner (`schedule.json`) covers up to `crunch_horizon_days`
(default `60`) working days ahead. Only pending **`task`** items are placed;
deadlines and events are date markers only. Assignment is greedy,
earliest-deadline-first (score breaks ties), respecting a per-day capacity
(`crunch_capacity_mode`: sum of priorities, or task count) and placing work
only on days `today ≤ day < reference date` (the due/event day itself is
no-work). Capacity is a **soft** target — the planner spreads overflow rather
than leaving tasks unscheduled when possible.

- `attend crunch` — open the board; auto-generates a plan on first run.
- `attend crunch --replan` — regenerate the whole plan from scratch.
- `attend crunch --undo` — restore the previous plan (single level of undo).
- `attend crunch move TASK_ID DATE` — manually reschedule (persisted; does **not**
  mark the plan stale).

Adding, completing, or cancelling tasks marks the plan **stale**; the board
shows a banner and `attend tasks` shows a `[!]` reminder until you
`attend crunch --replan`.

## Command reference

| Area | Command | Flags / subcommands |
|---|---|---|
| Daily | `day` | — |
| Daily | `log` | `--date DATE` |
| Daily | `holiday` | `--date DATE` |
| Daily | `summary` | compact semester overview |
| Bunks | `status` | optional `SUBJECT` |
| Bunks | `sim` | `SUBJECT N` |
| Bunks | `history` | optional `SUBJECT`, `--week N` |
| Bunks | `bunks` | `--subject CODE` |
| Subjects | `subjects` | — |
| Tasks | `add` | interactive |
| Tasks | `tasks` | `--tag`, `--subject`, `--kind task\|deadline\|event`, `--done`, `--cancelled` |
| Tasks | `done` | `ID` |
| Tasks | `cancel` | `ID` |
| Tasks | `show` | `ID` |
| Tasks | `crunch` | `--replan`, `--undo`; subcommand `move TASK_ID DATE` |
| Notes | `notes` | `--subject`, `--date`, `--week N` |
| Weeks | `weeks` | optional week number `N` to drill in |
| Weeks | `week` | read-only current week (no subcommand) |
| Weeks | `week set` | `N "goal text"` |
| Weeks | `week reflect` | `[N] "reflection text"` (omit `N` for current week) |
| Marks | `marks add` | `SUBJECT` |
| Marks | `marks` | optional `SUBJECT` |
| Output | `heatmap` | task-completion grid |
| Output | `export` | ZIP of CSVs → `~/.attendcli/attendcli_export_<timestamp>.zip` |
| Setup | `init` | — |
| Setup | `new-sem` | archive + wipe + re-init |
| Setup | `reset` | archive + wipe (no re-init) |
| Setup | `sem edit` | change semester end date |
| Setup | `timetable edit` | versioned Mon–Sat slot map in `$EDITOR` |
| Setup | `timeslots edit` | adjust slot start/end times only |
| Setup | `config edit` | global settings + per-subject reserve in `$EDITOR` |

Commands other than `init` and `config` require a initialized semester
(`attend init`).

## Dates & times

**Dates** accept `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `today` /
`yesterday` / `tomorrow`, and day names (`monday` … `sun` / `mon` …), which
resolve to the most recent past occurrence (today inclusive). Internally dates
are stored as `YYYY-MM-DD`.

**Times** accept `HH:MM` / `H:MM` (24h) and `HH:MM AM/PM` (12h, case
insensitive). Stored as 24h `HH:MM`. `attend day` displays slot times in 12h
`AM/PM` form.

Interactive prompts re-prompt on invalid input instead of crashing. Invalid
`--date` flags print a friendly one-liner (no traceback). Dates outside the
semester window prompt for confirmation in interactive flows (`attend log`,
`attend add`, `attend holiday`, etc.).

Set `ATTEND_TODAY=YYYY-MM-DD` to freeze "today" (useful for tests).

## Semester progression

- **`attend init`** — interactive setup: time structure, semester label and
  dates, subjects (code, name, alias, credits, reserve target), Mon–Fri
  timetable. Refuses to run when a semester already exists.
- **`attend new-sem`** — export + archive current data to
  `~/.attendcli_archive/sem_<start>/`, wipe `~/.attendcli/`, then run `init`.
- **`attend reset`** — same archive + wipe, without re-initializing.
- **`attend sem edit`** — change semester end date; week boxes regenerate
  (existing goals/reflections preserved).

**Saturday handling:** each Saturday, `attend day` and `attend log` ask whether
it is a working Saturday and, if yes, which weekday's timetable to follow. The
answer is stored in `daystate.json` so the same day is not re-asked. Sundays
are always non-working.

**Holidays:** `attend holiday [--date DATE]` marks all loggable slots that day
as cancelled (`C`) with no attendance effect. Rest days with no loggable slots
are a no-op. Already-logged days prompt before overwrite.

## Configuration

`attend config edit` opens settings and per-subject reserve targets in
`$EDITOR` (falls back to `$EDITOR` / `$VISUAL` / `vi`). Tunable settings:

| Setting | Default | Purpose |
|---|---|---|
| `rest_message` | (see `config.py`) | Shown on Sundays and non-working Saturdays |
| `editor` | `""` | Preferred editor for config/timetable edits |
| `urgency_decay` | `7.0` | `D` in `u = exp(D/d)` |
| `urgency_cap` | `100.0` | Maximum urgency multiplier |
| `no_due_default_days` | `30` | Default `d` for items without a reference date |
| `priority_min` / `priority_max` | `1` / `5` | Allowed priority range |
| `crunch_capacity_mode` | `priority_sum` | `priority_sum` or `task_count` |
| `crunch_daily_capacity` | `8` | Daily budget (priority sum or task count) |
| `crunch_skip_weekends` | `false` | Exclude Sat/Sun from crunch planning |
| `crunch_horizon_days` | `60` | How far ahead the planner considers |

`attend timeslots edit` adjusts only slot start/end times, preserving subject
assignments and writing a new timetable version effective today; older versions
keep their stored times.

The `attend weeks` strip uses `[■N■]` (current), `[✓N]` (past with reflection),
`[·N·]` (past without reflection), and `[ N ]` (upcoming).

## Data files (`~/.attendcli/`)

| File | Contents |
|---|---|
| `config.json` | Semester dates/label, subjects, time structure, settings |
| `timetable.json` | Version history; each version has `effective_from` and Mon–Sat slot map |
| `attendance.json` | Every logged slot: date, time, subject, status, reason, note, swap metadata |
| `tasks.json` | All tasks, deadlines, and events |
| `marks.json` | Marks components per subject |
| `weeks.json` | Week boxes: goal, reflection, start date |
| `notebox.json` | Notes from attended (`Y`) slots |
| `bunklog.json` | Reasons/notes from bunked (`N`) slots |
| `schedule.json` | Crunch plan (`current`/`previous`), stale flag |
| `daystate.json` | Working-Saturday decisions and holiday flags |

Archives from `new-sem` / `reset` live in `~/.attendcli_archive/sem_<start>/`
(including a timestamped export ZIP and the moved JSON files).

## Mobile access

No mobile app. Use Tailscale + SSH (Termius / Blink Shell) into your laptop for
an identical terminal experience.