"""
validate_schedule.py
--------------------
Validates the optimized schedule for a block against all constraints.
Run from the Scheduling_App folder:

    python validate_schedule.py [block_id]

If no block_id given, uses the most recently published block.
"""

import sqlite3
import json
import sys
from datetime import date as dt_date, timedelta
from collections import defaultdict

DATABASE = "ir_schedule.db"
ROTATION_SKILLS = {"IRC", "ECU"}
TL_SKILL        = "TL"
CALL_SKILL      = "Call"

PASS = "  ✓"
FAIL = "  ✗"
WARN = "  ⚠"


def get_pay_periods(block_start_str, block_end_str):
    start     = dt_date.fromisoformat(block_start_str)
    end       = dt_date.fromisoformat(block_end_str)
    days_back = (start.weekday() + 1) % 7
    p_start   = start - timedelta(days=days_back)
    periods   = []
    while p_start <= end:
        p_end = p_start + timedelta(days=13)
        periods.append((p_start, p_end))
        p_start = p_end + timedelta(days=1)
    return periods


def get_weeks(block_start_str, block_end_str):
    start   = dt_date.fromisoformat(block_start_str)
    end     = dt_date.fromisoformat(block_end_str)
    # Back to Sunday (weekday 6 in Python = Sunday, but isoweekday 7)
    days_to_sun = start.isoweekday() % 7  # Mon=1..Sat=6,Sun=0 → Sun=0
    w_start = start - timedelta(days=days_to_sun)
    weeks   = []
    while w_start <= end:
        w_end = w_start + timedelta(days=6)  # Sun + 6 = Sat
        weeks.append((w_start, w_end))
        w_start = w_end + timedelta(days=1)
    return weeks


def fte_target(fte):
    if fte >= 1.0:  return 8
    if fte >= 0.75: return 6
    return 5


def run(block_id):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    # Load block
    block = conn.execute(
        "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if not block:
        print(f"Block {block_id} not found.")
        return

    print(f"\n{'='*60}")
    print(f"Validating block: {block['name']} ({block['start_date']} → {block['end_date']})")
    print(f"Status: {block['status']}")
    print(f"{'='*60}")

    # Load result — optimized first, fall back to staff_requests
    opt = conn.execute(
        "SELECT result_json FROM optimized_schedule WHERE block_id = ?", (block_id,)
    ).fetchone()

    if opt and opt["result_json"]:
        print("Source: optimized_schedule")
        result = json.loads(opt["result_json"])
        unmet  = result.pop("unmet", {})
    else:
        print("Source: staff_requests (no optimized schedule found)")
        # Build result from staff_requests
        req_rows = conn.execute("""
            SELECT sr.date, sk.name as skill_name, st.name as staff_name
            FROM staff_requests sr
            JOIN skills sk ON sk.id = sr.skill_id
            JOIN staff st  ON st.id = sr.staff_id
            WHERE sr.block_id = ?
        """, (block_id,)).fetchall()

        result = {}
        for r in req_rows:
            if r["date"] not in result:
                result[r["date"]] = {}
            if r["skill_name"] not in result[r["date"]]:
                result[r["date"]][r["skill_name"]] = []
            result[r["date"]][r["skill_name"]].append(r["staff_name"])
        unmet = {}

    # Load reference data
    staff_rows = conn.execute("SELECT * FROM staff").fetchall()
    staff_by_name = {r["name"]: dict(r) for r in staff_rows}
    staff_by_id   = {r["id"]: dict(r) for r in staff_rows}

    skill_rows = conn.execute("SELECT * FROM skills").fetchall()
    skill_by_name = {r["name"]: dict(r) for r in skill_rows}
    skill_by_id   = {r["id"]: dict(r) for r in skill_rows}

    # Staff skills lookup: staff_name -> set of skill names
    staff_skills = defaultdict(set)
    for r in conn.execute("""
        SELECT st.name as staff, sk.name as skill
        FROM staff_skills ss
        JOIN staff st ON st.id = ss.staff_id
        JOIN skills sk ON sk.id = ss.skill_id
    """).fetchall():
        staff_skills[r["staff"]].add(r["skill"])

    # Minimums
    minimums = {}
    for r in conn.execute("""
        SELECT sk.name, sm.minimum_count
        FROM skill_minimums sm JOIN skills sk ON sk.id = sm.skill_id
    """).fetchall():
        minimums[r["name"]] = r["minimum_count"]

    # Unavailability: staff_name -> set of dates
    unavail = defaultdict(set)
    for r in conn.execute("""
        SELECT st.name, su.date
        FROM staff_unavailability su
        JOIN staff st ON st.id = su.staff_id
        WHERE su.block_id = ?
    """, (block_id,)).fetchall():
        unavail[r["name"]].add(r["date"])

    # ── Build assignment index ────────────────────────────────────────
    # assignments[date][skill] = [staff_names]
    # staff_dates[staff_name] = [(date, skill)]
    assignments  = defaultdict(lambda: defaultdict(list))
    staff_dates  = defaultdict(list)

    for date_str, day in result.items():
        for skill_name, names in day.items():
            for name in names:
                assignments[date_str][skill_name].append(name)
                staff_dates[name].append((date_str, skill_name))

    errors   = []
    warnings = []
    passes   = []

    # ── CHECK 1: No staff on more than one skill per day ─────────────
    print("\n[1] One skill per staff per day")
    found = False
    for date_str, day in result.items():
        seen = defaultdict(list)
        for skill_name, names in day.items():
            for name in names:
                seen[name].append(skill_name)
        for name, skills_assigned in seen.items():
            if len(skills_assigned) > 1:
                errors.append(f"{date_str}: {name} assigned to multiple skills: {skills_assigned}")
                found = True
    if not found:
        passes.append("All staff assigned to at most one skill per day")
        print(f"{PASS} All clear")
    else:
        for e in errors[-5:]:
            print(f"{FAIL} {e}")

    # ── CHECK 2: TL not assigned to other skills same day ────────────
    print("\n[2] TL exclusivity")
    found = False
    for date_str, day in result.items():
        tl_names = set(day.get(TL_SKILL, []))
        for skill_name, names in day.items():
            if skill_name == TL_SKILL:
                continue
            for name in names:
                if name in tl_names:
                    errors.append(f"{date_str}: {name} is TL but also assigned {skill_name}")
                    found = True
    if not found:
        print(f"{PASS} All clear")
    else:
        for e in errors[-5:]:
            print(f"{FAIL} {e}")

    # ── CHECK 3: No unavailable staff assigned ───────────────────────
    print("\n[3] Unavailability respected")
    found = False
    for name, dates_skills in staff_dates.items():
        for date_str, skill_name in dates_skills:
            if date_str in unavail[name]:
                errors.append(f"{date_str}: {name} is unavailable but assigned {skill_name}")
                found = True
    if not found:
        print(f"{PASS} All clear")
    else:
        for e in errors[-5:]:
            print(f"{FAIL} {e}")

    # ── CHECK 4: Staff have the required skill ───────────────────────
    print("\n[4] Staff skill eligibility")
    found = False
    for date_str, day in result.items():
        for skill_name, names in day.items():
            if skill_name == CALL_SKILL:
                continue  # Call is open to all
            for name in names:
                if name not in staff_skills:
                    errors.append(f"{date_str}: {name} not found in staff_skills")
                    found = True
                elif skill_name not in staff_skills[name]:
                    errors.append(f"{date_str}: {name} assigned {skill_name} but doesn't have that skill")
                    found = True
    if not found:
        print(f"{PASS} All clear")
    else:
        for e in errors[-5:]:
            print(f"{FAIL} {e}")

    # ── CHECK 5: Bare minimums met ───────────────────────────────────
    print("\n[5] Bare minimums")
    min_violations = []
    for date_str, day in result.items():
        d = dt_date.fromisoformat(date_str)
        if d.weekday() >= 5:
            continue  # skip weekends
        for skill_name, minimum in minimums.items():
            count = len(day.get(skill_name, []))
            if count < minimum:
                min_violations.append(
                    f"{date_str} ({d.strftime('%a')}): {skill_name} has {count}/{minimum}"
                )
    if not min_violations:
        print(f"{PASS} All minimums met")
    else:
        print(f"{FAIL} {len(min_violations)} minimum violations:")
        for v in min_violations[:10]:
            print(f"       {v}")
        if len(min_violations) > 10:
            print(f"       ... and {len(min_violations)-10} more")

    # ── CHECK 6: FTE floor and ceiling ──────────────────────────────
    print("\n[6] FTE compliance (shifts = target - unavailable days)")
    fte_violations = []
    pay_periods    = get_pay_periods(block["start_date"], block["end_date"])

    for name, s in staff_by_name.items():
        target   = fte_target(s["fte"])
        worked   = {d for d, _ in staff_dates[name]}
        off      = unavail[name]

        for i, (p_start, p_end) in enumerate(pay_periods):
            weekdays = set()
            d = p_start
            while d <= p_end:
                if d.weekday() < 5:
                    weekdays.add(d.isoformat())
                d += timedelta(days=1)

            shifts    = len(worked & weekdays)
            unavail_c = len(off & weekdays)
            required  = max(0, target - unavail_c)
            total     = shifts + unavail_c

            if shifts != required:
                fte_violations.append(
                    f"{name} (FTE {s['fte']}): PP{i+1} "
                    f"worked {shifts}, unavail {unavail_c}, "
                    f"required {required} shifts (target {target})"
                )

    if not fte_violations:
        print(f"{PASS} All staff at correct FTE")
    else:
        print(f"{FAIL} {len(fte_violations)} FTE violations:")
        for v in fte_violations[:10]:
            print(f"       {v}")
        if len(fte_violations) > 10:
            print(f"       ... and {len(fte_violations)-10} more")

    # ── CHECK 7: Rotation fairness ───────────────────────────────────
    print("\n[7] Rotation fairness (IRC / ECU)")
    weeks = get_weeks(block["start_date"], block["end_date"])

    for rot_skill in sorted(ROTATION_SKILLS):
        eligible = [n for n, skills in staff_skills.items() if rot_skill in skills]
        if not eligible:
            continue

        print(f"\n  {rot_skill} — eligible: {', '.join(sorted(eligible))}")

        # Weekly counts
        weekly_counts = defaultdict(lambda: defaultdict(int))
        for date_str, day in result.items():
            for name in day.get(rot_skill, []):
                d = dt_date.fromisoformat(date_str)
                for wi, (w_start, w_end) in enumerate(weeks):
                    if w_start <= d <= w_end:
                        weekly_counts[wi][name] += 1

        multi_week = []
        for wi, counts in weekly_counts.items():
            for name, count in counts.items():
                if count > 1:
                    multi_week.append(
                        f"    Week {wi+1}: {name} did {rot_skill} {count}x"
                    )

        if multi_week:
            print(f"  {WARN} Multiple assignments same week:")
            for m in multi_week:
                print(m)
        else:
            print(f"  {PASS} No one assigned {rot_skill} more than once per week")

        # Pay period counts
        pp_counts = defaultdict(lambda: defaultdict(int))
        for date_str, day in result.items():
            for name in day.get(rot_skill, []):
                d = dt_date.fromisoformat(date_str)
                for pi, (p_start, p_end) in enumerate(pay_periods):
                    if p_start <= d <= p_end:
                        pp_counts[pi][name] += 1

        print(f"\n  Pay period distribution:")
        for pi, (p_start, p_end) in enumerate(pay_periods):
            counts = {n: pp_counts[pi].get(n, 0) for n in eligible}
            vals   = list(counts.values())
            spread = max(vals) - min(vals)
            flag   = WARN if spread > 1 else PASS
            row    = ", ".join(f"{n.split()[0]}:{v}" for n, v in sorted(counts.items()))
            print(f"  {flag} PP{pi+1}: [{row}] spread={spread}")

        # Block totals
        block_counts = {n: sum(pp_counts[pi].get(n, 0) for pi in range(len(pay_periods))) for n in eligible}
        vals   = list(block_counts.values())
        spread = max(vals) - min(vals)
        flag   = WARN if spread > 2 else PASS
        row    = ", ".join(f"{n.split()[0]}:{v}" for n, v in sorted(block_counts.items()))
        print(f"  {flag} Block total: [{row}] spread={spread}")

    # ── SUMMARY ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_errors = len([e for e in errors]) + len(min_violations) + len(fte_violations)
    if total_errors == 0:
        print(f"{PASS} All hard constraints satisfied.")
    else:
        print(f"{FAIL} {total_errors} constraint violation(s) found.")

    if unmet:
        unmet_count = sum(len(v) for v in unmet.values() if v)
        if unmet_count:
            print(f"{WARN} {unmet_count} unmet staffing need(s) reported by optimizer.")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        bid = int(sys.argv[1])
    else:
        # Use most recently created block (any status)
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, name, status FROM schedule_blocks ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            print("No blocks found. Pass a block_id as argument.")
            sys.exit(1)
        print(f"No block_id given — using most recent block: {row['name']} (id={row['id']}, status={row['status']})")
        bid = row["id"]

    run(bid)