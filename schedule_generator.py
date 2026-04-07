"""
schedule_generator.py
---------------------
Generates a monthly schedule by walking every calendar day in the month,
skipping closed dates, and mapping each open day to the weekly template
using that day's name (Monday, Tuesday, etc.).

Fill order:
  - Days are filled in day-priority order (lower = first)
  - Within each day, skills are filled in skill-priority order (lower = first)
  - Staff are chosen by fewest shifts so far (fairness), then highest FTE (tiebreaker)
  - One staff member can only fill one skill slot per calendar day

Result structure:
  {
    "2025-07-01": { skill_name: [staff_name, ...], ... },
    "2025-07-02": { ... },
    ...
    "unmet": { "2025-07-01": { skill_name: shortage_count }, ... }
  }
"""

import sqlite3
import calendar
from datetime import date as dt_date, timedelta

DATABASE = "ir_schedule.db"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_data(conn):
    skills = conn.execute("""
        SELECT id, name, priority FROM skills
        ORDER BY CASE WHEN priority = 0 THEN 999 ELSE priority END, name
    """).fetchall()

    day_rows = conn.execute("SELECT day_of_week, priority FROM day_priority").fetchall()
    day_priorities = {row["day_of_week"]: row["priority"] for row in day_rows}

    need_rows = conn.execute("""
        SELECT day_of_week, skill_id, quantity
        FROM template_needs WHERE template_id = 1
    """).fetchall()
    needs = {day: {} for day in DAYS}
    for row in need_rows:
        needs[row["day_of_week"]][row["skill_id"]] = row["quantity"]

    staff_rows = conn.execute("SELECT id, name, fte FROM staff ORDER BY name").fetchall()
    staff = []
    for s in staff_rows:
        skill_ids = set(
            r["skill_id"] for r in conn.execute(
                "SELECT skill_id FROM staff_skills WHERE staff_id = ?", (s["id"],)
            ).fetchall()
        )
        staff.append({"id": s["id"], "name": s["name"], "fte": s["fte"], "skill_ids": skill_ids})

    return skills, day_priorities, needs, staff


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def generate_month(conn, month_start: dt_date, closed: set):
    """
    Generate a schedule for the entire month containing month_start.
    closed: set of ISO date strings to skip (e.g. {"2025-07-04"}).
    Returns result dict keyed by ISO date string + "unmet" key.
    """
    skills, day_priorities, needs, staff = _load_data(conn)

    # All calendar days in the month
    year  = month_start.year
    month = month_start.month
    _, days_in_month = calendar.monthrange(year, month)
    all_dates = [dt_date(year, month, d) for d in range(1, days_in_month + 1)]

    # Open dates: not closed, and has template needs for that weekday
    open_dates = [
        d for d in all_dates
        if d.isoformat() not in closed
        and needs.get(d.strftime("%A"))
    ]

    # Sort open dates by (day-of-week priority, then calendar date)
    open_dates_sorted = sorted(
        open_dates,
        key=lambda d: (
            day_priorities.get(d.strftime("%A"), 0) or 999,
            d
        )
    )

    # shift_counts resets each week (Mon–Sun) for fairness within the week
    # We track per-calendar-week: week_number -> {staff_id: count}
    week_shift_counts = {}

    schedule = {}
    unmet    = {}

    for d in open_dates_sorted:
        date_str = d.isoformat()
        day_name = d.strftime("%A")
        week_num = d.isocalendar()[1]  # ISO week number

        if week_num not in week_shift_counts:
            week_shift_counts[week_num] = {s["id"]: 0 for s in staff}
        shift_counts = week_shift_counts[week_num]

        day_needs      = needs.get(day_name, {})
        assigned_today = set()

        schedule[date_str] = {}
        unmet[date_str]    = {}

        for skill in skills:
            skill_id   = skill["id"]
            skill_name = skill["name"]
            quantity   = day_needs.get(skill_id, 0)
            if quantity == 0:
                continue

            schedule[date_str].setdefault(skill_name, [])
            shortage = 0

            candidates = sorted(
                [s for s in staff
                 if skill_id in s["skill_ids"] and s["id"] not in assigned_today],
                key=lambda s: (shift_counts[s["id"]], -s["fte"])
            )

            for _ in range(quantity):
                if candidates:
                    chosen = candidates.pop(0)
                    schedule[date_str][skill_name].append(chosen["name"])
                    assigned_today.add(chosen["id"])
                    shift_counts[chosen["id"]] += 1
                else:
                    shortage += 1

            if shortage:
                unmet[date_str][skill_name] = shortage

    schedule["unmet"] = unmet
    return schedule


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import datetime
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    today       = datetime.date.today()
    month_start = datetime.date(today.year, today.month, 1)
    result      = generate_month(conn, month_start, set())
    conn.close()

    unmet = result.pop("unmet")
    for date_str in sorted(k for k in result if k != "unmet"):
        day_sched = result[date_str]
        if not day_sched:
            continue
        print(f"\n{date_str}")
        for skill, names in day_sched.items():
            print(f"  {skill}: {', '.join(names)}")

    print("\n--- Unmet needs ---")
    any_unmet = False
    for date_str, day_unmet in unmet.items():
        for skill, count in day_unmet.items():
            print(f"  {date_str} / {skill}: {count} unfilled")
            any_unmet = True
    if not any_unmet:
        print("  None")