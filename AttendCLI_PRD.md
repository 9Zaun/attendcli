# AttendCLI — Project Requirements Document

> Terminal-first, locally-run academic survival system for Indian private college students.
> All data lives on disk. No cloud. No GUI. No web server.
> Built in Python with `rich` for terminal rendering.

---

## Design Philosophy

- **Daily friction must be near-zero.** The entire system is designed around two commands: `attend day` in the morning and `attend log` at night. Everything else is on-demand analysis.
- **Track accurately, bunk strategically.** The bunk economy is derived directly from the 75% constraint — not an approximation of it.
- **Nothing is ever deleted.** Cancelled tasks, bunked classes, and old timetable versions all stay in history. The export is a full audit.
- **Portable and personal.** The app works on any laptop. Mobile access is via SSH, not a separate app.

---

## 1. Semester Setup & Initialization (`attend init`)

### 1.1 What initialization collects

Run once at the start of each semester. Collected in order:

1. **Time structure** — the fixed daily schedule skeleton: list of time slots with their times (e.g., 09:00, 10:00, 11:00 ...). This does not change across the semester. It is asked once, saved, and never asked again unless the user explicitly edits it.
2. **Semester start date** and **tentative end date** — used to generate week boxes. End date is editable at any time via `attend sem edit`.
3. **Subjects** — for each subject:
   - Name and short code (e.g., `DSA`, `DBMS`)
   - Credit value (stored for the marks/risk section)
   - Reserve bunk count (integer; the number of bunk tokens the user wants to keep untouched as an emergency reserve)
4. **Timetable** — filled in slot by slot, Monday through Friday:
   - Each time slot in the structure is assigned one of: a subject code, `tutorial-slot`, `break`, or `lunch`.
   - Breaks and lunch are displayed in the day view but never logged.
   - Tutorial slots are a special object that must be resolved at log time each day.

### 1.2 Saturday handling

Saturdays are not assumed to be academic holidays. Each Saturday, when the user runs `attend day` or `attend log`, the app asks:

- "Is today a working Saturday? (y/n)"
- If yes: "Which day's timetable does it follow?" (e.g., Monday)
- That day's timetable is used for the session.
- The answer is stored so re-running the same day does not re-ask.

Sundays are always non-working. On Sundays (and non-working Saturdays), the day view shows a configurable rest message instead of a schedule.

### 1.3 Holiday declaration

At any point, the user can run `attend holiday [--date DATE]` to declare a full college holiday for a given date (default: today). This marks the entire day as cancelled with no attendance implications. All slots for that day are stored as `C` (cancelled) automatically.

### 1.4 Editability

- `attend sem edit` — change semester end date; week boxes regenerate (existing goal/reflection content preserved).
- `attend timetable edit` — opens timetable in `$EDITOR`; saves a new version with `effective_from = today`. Previous versions preserved in history.
- `attend timeslots edit` — adjust **only** the slot start/end times without rebuilding the timetable. Subject assignments are preserved (their times shift). A new timetable version is written effective from today; older versions keep their stored times, so historical attendance is unaffected.
- `attend config edit` — change global settings: rest-day message, default editor, reserve bunk per subject, etc.
- Time structure itself can be edited via `attend timeslots edit` (or `attend config edit`) but is intentionally not prompted on every initialization.

---

## 2. Timetable Engine

### 2.1 Slot types

| Type | Description |
|---|---|
| `subject` | Any class (lecture, lab, practical — all treated identically for attendance) |
| `tutorial-slot` | Unresolved; must be claimed or cancelled at log time each day |
| `break` | Shown in day view, never logged |
| `lunch` | Shown in day view, never logged |

Labs and lectures are **not** distinguished. A professor can and regularly does switch between them. All that matters for the attendance engine is: did the slot happen, and under which subject?

### 2.2 Subject swapping

Any slot (not just tutorials) can be **swapped** at log time. When the user enters `S` (swapped) during logging:

- The app asks: "Which subject was actually taught?"
- The user enters a subject code.
- The app then asks `Y / N / C` for that substituted subject.
- Attendance is credited/debited to the substituted subject, not the scheduled one.
- The original scheduled subject's slot is recorded as a swap event (for history and export).

This means the attendance engine is **independent of the timetable** for calculation purposes. The timetable drives the daily prompts and display; the engine simply receives `(date, subject, status)` events regardless of how they were generated.

### 2.3 Tutorial slot resolution

At log time, when a `tutorial-slot` is encountered:

- If no professor claimed it: user enters `-1` → slot is recorded as cancelled (neutral, no attendance effect).
- If a professor claimed it: user inputs the subject code, then logs `Y / N / C` for that subject.

Tutorials can morph into any subject or be cancelled — both paths are supported.

### 2.4 Timetable versioning

Each time `attend timetable edit` is saved:

- A new version entry is added to `timetable.json` with `effective_from = today`.
- All date-based queries select the version where `effective_from` is the latest date ≤ the query date.
- Old versions remain intact and are used for historical log reconstruction.

---

## 3. Daily Attendance Logging (`attend log`)

### 3.1 Flow

- Default date: today. Override: `--date YYYY-MM-DD` or `--date yesterday`.
- If the previous working day is unlogged, a reminder is shown before proceeding.
- Fetch that day's timetable version (correct version for that date).
- Walk through loggable slots in chronological order (breaks and lunch skipped).
- For each slot, the user enters one of:

| Input | Meaning | Effect |
|---|---|---|
| `Y` | Attended | Adds 1 to present count (`P`) |
| `N` | Bunked voluntarily | Adds 1 to absent count (`A`); prompts optional reason and optional note |
| `C` | Cancelled by college | Neutral; no effect on `P` or `A` |
| `S` | Subject was swapped | Asks for the actual subject, then prompts `Y / N / C` for that subject |

### 3.2 Note fields

- **Y note** (optional): a free-text note attached to an attended slot. Could be "prof covered trees", "taught sorting algorithms" — anything. These notes feed into the **Notebox** feature.
- **N note** (optional): a free-text note attached to a bunked slot. Separate from the reason field (reason = why you bunked; note = what you might want to record about the missed class). These feed into a dedicated **Bunk Log** section.
- **N reason** (optional): a short tag-style reason for bunking (e.g., "project work", "unwell"). Stored separately from the note.

### 3.3 Post-log summary

After processing all slots, the app prints a compact summary:

```
DSA     slack: 4 → 1   safe bunks: 1 → 0   ⚠ 1 reserve used
DBMS    slack: 6 → 7   safe bunks: 2 → 2
C Lab   [C] no change
```

---

## 4. Bunk Economy

### 4.1 Core model

The system is derived directly from the 75% attendance rule. Per subject, the state is:

- `P` = total present count (Y slots)
- `A` = total absent count (N slots)
- `slack = P - 3 * A`

Properties:
- **Present** → `P += 1`, `slack += 1`
- **Absent** → `A += 1`, `slack -= 3`
- **Cancelled** → no change to either
- Currently safe iff `slack >= 0`
- Can safely bunk the next class iff `slack >= 3`

**Safe bunks available** (how many more you can bunk right now without dropping below 75%):

\[ \text{safe\_bunks} = \max(0,\ \lfloor \text{slack} / 3 \rfloor) \]

**Reserve bunks** (configured per subject at init): a fixed number subtracted from safe bunks to maintain an emergency buffer. These are never automatically spent.

\[ \text{spendable\_bunks} = \max(0,\ \text{safe\_bunks} - \text{reserve}) \]

The display bar for each subject has three visual segments:
- Full bar width = raw safe bunk potential (based on current P)
- Middle segment = spendable bunks
- End segment = reserve bunks (visually distinguished)

### 4.2 Negative slack and guardrails

Negative slack is fully supported (it means you are already below 75%). The system:

- Warns when `slack < 0`: "You are currently below 75% in [subject]. You need N more consecutive attends to recover."
- Warns when `slack == 0`: "At the floor. Any absence risks falling below 75%."
- Hard guardrail: the app computes and displays the **minimum consecutive classes you must attend** to return to safety, given remaining total classes in the semester.
- If it is mathematically impossible to recover (i.e., required attends > remaining classes), an explicit critical warning is shown: "Cannot recover [subject] this semester."

### 4.3 Per-subject tracking

All bunk calculations are fully per-subject. No global aggregation is shown by default. On `attend day`, each subject's slack and spendable bunk count is shown inline beside the subject in the schedule.

---

## 5. Daily Dashboard (`attend day`)

The output of `attend day` is a single terminal print with these sections, in order:

1. **Header bar** — date, day of week, week number out of total (e.g., `Wed · Aug 28 · Week 6 of 17`)
2. **Today's schedule** — all time slots in order (including breaks and lunch, which are shown but labelled as non-loggable). Slot times are displayed in 12-hour `HH:MM AM/PM` format (stored internally as 24h). Each loggable subject shows its current slack and spendable bunk count inline.
3. **Upcoming tasks/deadlines/events** — items due within the next 7 days, sorted by priority × urgency score (see §6.2). Shows type, title, subject, due date, priority, tags.
4. **Current week goal** — one-line display of the current week box's goal text (if set).
5. **Rest-day message** — shown instead of everything above on Sundays and non-working Saturdays.

The entire output is read-only. No prompts. Quick scan only.

---

## 6. Task / Deadline / Event System

### 6.1 Item types

Three distinct kinds, all stored in `tasks.json`:

| Kind | Purpose | Has due date | Has event time |
|---|---|---|---|
| `task` | Actual work to be done | Optional | No |
| `deadline` | A submission/due date | Yes (required) | No |
| `event` | One-off scheduled occurrence (test, presentation, viva) | No | Yes (required) |

A **task** can be linked to a **deadline** or an **event** via a `linked_to` ID. When linked, the task inherits the linked item's date as its urgency reference point.

Each item has:
- `id` (auto-generated)
- `kind`
- `subject` (optional for personal tasks)
- `title`
- `due` / `event_time` as applicable
- `priority` (integer 1–4; 4 = highest)
- `tags` (freeform list; no predefined taxonomy)
- `status`: `pending`, `done`, or `cancelled`
- `notes` (free-text field; any context the user wants to attach)
- `effort` (integer 1–4; 4 = most effort required; used by the crunch scheduler)
- `created_at`

### 6.2 Priority × urgency ranking

The sort key for tasks is a combined score where urgency grows exponentially as the deadline approaches, eventually overpowering priority:

Let:
- `p` = priority value (1–4)
- `d` = days until due date (clamped to minimum 0.5 to avoid division issues)
- `D` = a decay constant (suggested default: 7, configurable)

Urgency component:

\[ u = e^{D / d} \]

Combined score:

\[ \text{score} = p \times u \]

Items are sorted by `score` descending. This means:
- A high-priority item far away ranks below a low-priority item due tomorrow, once `d` is small enough.
- The crossover point where urgency dominates is tunable via `D`.

For tasks with **no due date** (standalone tasks not linked to a deadline/event), `d` is set to a large default (e.g., 30 days) so they rank by priority only until manually assigned a deadline.

### 6.3 Commands

- `attend add` — interactive creation flow (kind → subject → title → due/event time → priority → tags → notes → effort)
- `attend tasks [--tag TAG] [--subject CODE] [--kind KIND]` — show pending items sorted by score
- `attend done ID` — mark complete
- `attend cancel ID` — mark cancelled (preserved in history)
- `attend show ID` — display full item details including notes

### 6.4 Crunch scheduler (`attend crunch`)

An algorithm that takes all pending tasks and produces a recommended day-by-day work schedule for the coming weeks. Each task has `effort` (1–4) and a due date. The algorithm:

1. Sorts tasks by score (priority × urgency).
2. Assigns tasks to available days (weekdays, starting from today) by filling each day's effort budget (configurable max daily effort units).
3. Respects due dates — no task is scheduled after its due date.
4. Flags tasks that cannot be fit before their deadline given current backlog.

The output of `attend crunch` is a **scheduled plan view**: day-by-day listing of what to work on and for how long (based on effort units).

**Undo support:** the previously generated crunch plan is stored. `attend crunch --undo` reverts to the previous plan. Manually dragging tasks between days in the plan view is supported via `attend crunch move TASK_ID DATE`.

The algorithm is intentionally simple (greedy by score, constrained by effort budget and deadlines). The goal is a useful starting point the user can adjust, not a perfect optimizer.

---

## 7. Notebox & Bunk Log

### 7.1 Notebox

A searchable store of all notes attached to **attended** slots during logging. Each note entry contains:

- Date
- Time slot
- Subject
- The note text

`attend notes [--subject CODE] [--date DATE] [--week N]` — view and filter notes.

This functions as a personal class journal that builds itself over the semester.

### 7.2 Bunk Log

A separate store of all notes and reasons attached to **bunked** slots. Each entry contains:

- Date
- Time slot
- Subject
- Reason (if given)
- Note (if given)

`attend bunks [--subject CODE]` — view the full bunk history for retrospective review and catch-up planning.

---

## 8. Week Box System

### 8.1 Structure

Weeks are generated from `semester_start` to `semester_end`. Each week has:
- `week_number`
- `start_date`
- `goal` (set before or during the week)
- `reflection` (added after)

### 8.2 Display (`attend weeks`)

The top of the output shows a visual strip of numbered boxes:

```
[✓1] [·2·] [✓3] [✓4] [·5·] [■6■] [ 7 ] [ 8 ] ... [17]
```

The implemented strip is more informative than the original sketch — it surfaces
whether a past week has a written reflection:

- Current week: highlighted (e.g., `[■6■]`).
- Past week **with** a reflection ("done"): `[✓N]`.
- Past week **without** a reflection: `[·N·]`.
- Future weeks: empty brackets (e.g., `[ 7 ]`).

A legend is printed beneath the strip. Entering a week number shows that week's
goal and reflection (if set), along with tasks/events that fell within that week.

`attend week` (no subcommand) is a **read-only** display of the current week.
Editing is done explicitly via `attend week set N "goal"` and
`attend week reflect [N] "text"`.

### 8.3 Commands

- `attend week set N "goal text"` — set a week's goal
- `attend week reflect [N] "reflection text"` — add/edit reflection (defaults to current week if N omitted)
- Entering a week number in the weeks view: `attend weeks 6` — drill into that week's detail

---

## 9. Marks Logging

No automatic CGPA calculation. This section is purely for **logging and reference**.

On initialization, each subject is given a `credits` field. In the marks section:

- `attend marks add SUBJECT` — interactive:
  - Component name (e.g., "midterm", "quiz 1", "assignment 2", "project presentation" — fully freeform)
  - Score (e.g., `18/20`)
  - Optional weightage (leave blank if unknown)
  - Optional notes
- `attend marks [SUBJECT]` — show all logged components for a subject with scores, weightages (if set), and credits as a reminder of the subject's importance.

No automatic risk calculation. The credits field is surfaced to remind the user which subjects matter more — beyond that, no formula is imposed.

---

## 10. Heatmap (`attend heatmap`)

A terminal-rendered grid where:

- Each **column** = one week of the semester
- Each **row** = a day of the week (Mon–Sat)
- Each **cell** = one day

Cell color/character intensity is determined by **number of tasks completed** that day, not attendance. Attendance is a baseline requirement; completing tasks represents actual productive output.

| Tasks completed | Cell appearance |
|---|---|
| 0 | `·` (faint/empty) |
| 1 | `░` |
| 2 | `▒` |
| 3 | `▓` |
| 4+ | `█` |

Rendered using Unicode block characters. Works in any modern terminal.

---

## 11. Data Files (stored in `~/.attendcli/`)

| File | Contents |
|---|---|
| `config.json` | Semester dates, subject list (names, codes, credits, reserve bunks), time structure, global settings |
| `timetable.json` | Version history array; each version has `effective_from` and full Mon–Sat slot map |
| `attendance.json` | Every logged slot: date, time, subject, status, reason, note, swap metadata |
| `tasks.json` | All tasks, deadlines, and events with full metadata |
| `marks.json` | All marks entries per subject |
| `weeks.json` | Week box records: goal, reflection, start date per week |
| `notebox.json` | All Y-slot notes extracted for the notebox view |
| `bunklog.json` | All N-slot reasons and notes extracted for the bunk log view |

All files are plain JSON. Human-readable and directly inspectable.

---

## 12. Export (`attend export`)

Generates a structured export of everything. Output format: **CSV per category** (one ZIP containing multiple well-formatted CSVs), readable by any spreadsheet app.

Files exported:

| CSV file | Contents |
|---|---|
| `attendance_summary.csv` | Per-subject: P, A, C, slack, safe bunks, spendable bunks, reserve |
| `attendance_log.csv` | Full session log: date, time, subject, status, reason, note, swap info |
| `tasks.csv` | All tasks/deadlines/events with all fields including notes and completion status |
| `marks.csv` | All marks entries per subject and component |
| `weeks.csv` | All week boxes: week number, dates, goal, reflection |
| `notebox.csv` | All class notes: date, time, subject, note text |
| `bunklog.csv` | All bunk entries: date, time, subject, reason, note |
| `heatmap.csv` | Day-by-day task completion counts (raw data behind the heatmap) |
| `timetable_history.csv` | All timetable versions with effective dates |

---

## 13. Mobile Access

No mobile app is built. Mobile access is via:

1. Install **Tailscale** on the laptop and on the iPhone.
2. SSH into the laptop from anywhere using **Termius** (iOS) or **Blink Shell**.
3. The terminal app is fully accessible over SSH — identical experience.

---

## 14. Complete Command Reference

### Core daily
| Command | Purpose |
|---|---|
| `attend day` | Full daily dashboard (read-only) |
| `attend log [--date DATE]` | End-of-day Y/N/C/S logging flow |
| `attend holiday [--date DATE]` | Declare a full holiday for a given day |

### Attendance & bunks
| Command | Purpose |
|---|---|
| `attend status [SUBJECT]` | Per-subject bunk economy table |
| `attend sim SUBJECT N` | Simulate bunking N more classes of a subject |
| `attend history [SUBJECT] [--week N]` | Chronological attendance log, filterable |
| `attend bunks [--subject CODE]` | View bunk log with reasons and notes |

### Tasks
| Command | Purpose |
|---|---|
| `attend add` | Interactive task/deadline/event creation |
| `attend tasks [--tag TAG] [--subject CODE] [--kind KIND]` | View pending items sorted by priority × urgency |
| `attend done ID` | Mark item complete |
| `attend cancel ID` | Mark item cancelled |
| `attend show ID` | Show full item detail including notes |
| `attend crunch` | Generate scheduled plan from pending tasks |
| `attend crunch --undo` | Revert to previous crunch plan |
| `attend crunch move TASK_ID DATE` | Manually reschedule a task in the plan |

### Notes
| Command | Purpose |
|---|---|
| `attend notes [--subject CODE] [--date DATE] [--week N]` | View Notebox entries |

### Weeks
| Command | Purpose |
|---|---|
| `attend weeks [N]` | Full week box strip; optionally drill into week N |
| `attend week set N "text"` | Set a week's goal |
| `attend week reflect [N] "text"` | Add/edit reflection for a week |

### Marks
| Command | Purpose |
|---|---|
| `attend marks add SUBJECT` | Log a marks component interactively |
| `attend marks [SUBJECT]` | View marks log for one or all subjects |

### Heatmap & export
| Command | Purpose |
|---|---|
| `attend heatmap` | Render terminal heatmap (task completion intensity) |
| `attend export` | Generate full ZIP of all CSVs |

### Setup & config
| Command | Purpose |
|---|---|
| `attend init` | Initialize a new semester |
| `attend sem edit` | Edit semester end date |
| `attend timetable edit` | Edit timetable (versioned) |
| `attend timeslots edit` | Edit slot times only (keeps subjects; versioned) |
| `attend config edit` | Edit global config |

---

## 15. Out of Scope (deliberately excluded)

- WhatsApp bot integration
- GUI or web interface of any kind
- Notifications or background daemons
- Automatic CGPA calculation
- Cloud sync or remote database
- iOS/Android app
