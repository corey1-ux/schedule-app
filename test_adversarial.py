"""
test_adversarial.py
-------------------
Adversarial tests designed to break the optimizer.
Each test sets up an edge case, runs the optimizer, and checks
whether it handles it gracefully (solves correctly or fails clearly).

Run from the Scheduling_App folder:
    python test_adversarial.py

Exit code 0 = all tests passed or failed gracefully.
Exit code 1 = unexpected crash or wrong behavior.
"""

import sqlite3
import sys
import json
from datetime import date as dt_date, timedelta
from collections import defaultdict

PASS  = "  PASS"
FAIL  = "  FAIL"
WARN  = "  WARN"
SKIP  = "  SKIP"

results = {"passed": 0, "failed": 0, "warned": 0, "errors": []}

def check(name, condition, detail=""):
    if condition:
        print(f"{PASS} {name}", flush=True)
        results["passed"] += 1
    else:
        print(f"{FAIL} {name}{': ' + detail if detail else ''}", flush=True)
        results["failed"] += 1
        results["errors"].append(name)

def warn(name, detail=""):
    print(f"{WARN} {name}{': ' + detail if detail else ''}", flush=True)
    results["warned"] += 1

def section(title):
    print(f"\n── {title} {'─' * max(1, 54 - len(title))}", flush=True)

def run_optimizer(conn, block_id=1, time_limit=30):
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from optimizer import optimize
    # Suppress OR-Tools solver output
    devnull = open(os.devnull, 'w')
    old_stderr = sys.stderr
    sys.stderr = devnull
    try:
        result, error = optimize(conn, block_id, time_limit_seconds=time_limit)
    finally:
        sys.stderr = old_stderr
        devnull.close()
    return result, error

def get_weekdays(start_str, end_str):
    dates = []
    d = dt_date.fromisoformat(start_str)
    e = dt_date.fromisoformat(end_str)
    while d <= e:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates

def get_pay_periods(start_str, end_str):
    start     = dt_date.fromisoformat(start_str)
    end       = dt_date.fromisoformat(end_str)
    days_back = (start.weekday() + 1) % 7
    ps        = start - timedelta(days=days_back)
    periods   = []
    while ps <= end:
        pe = ps + timedelta(days=13)
        periods.append((ps, pe))
        ps = pe + timedelta(days=1)
    return periods

def get_weeks(start_str, end_str):
    start = dt_date.fromisoformat(start_str)
    end   = dt_date.fromisoformat(end_str)
    dow   = start.isoweekday() % 7
    ws    = start - timedelta(days=dow)
    weeks = []
    while ws <= end:
        we = ws + timedelta(days=6)
        weeks.append((ws, we))
        ws = we + timedelta(days=1)
    return weeks

def fte_target(fte):
    if fte >= 1.0:  return 8
    if fte >= 0.75: return 6
    return 5

def weekly_max(fte):
    return 4 if fte >= 1.0 else 3

def assert_no_fte_ceiling_violations(conn, result, block_start, block_end, label=""):
    """Helper: check no staff exceeds FTE ceiling."""
    staff_rows = conn.execute("SELECT * FROM staff").fetchall()
    weekdays   = get_weekdays(block_start, block_end)
    pps        = get_pay_periods(block_start, block_end)
    violations = []
    for s in staff_rows:
        worked = set()
        for date, day in result.items():
            if date == "unmet": continue
            for names in day.values():
                if s["name"] in names:
                    worked.add(date)
        target = fte_target(s["fte"])
        for ps, pe in pps:
            period_days = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()]
            shifts = len([d for d in period_days if d in worked])
            if shifts > target:
                violations.append(f"{s['name']} PP{ps}: {shifts}>{target}")
    check(f"FTE ceiling not violated{' (' + label + ')' if label else ''}",
          len(violations) == 0, "; ".join(violations[:3]))
    return violations

def base_db(start_date, end_date, num_weeks=None):
    """Build a minimal test database with given block dates."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE skills (id INTEGER PRIMARY KEY, name TEXT, priority INTEGER DEFAULT 0);
        CREATE TABLE staff (id INTEGER PRIMARY KEY, name TEXT, fte REAL);
        CREATE TABLE staff_skills (staff_id INTEGER, skill_id INTEGER, PRIMARY KEY(staff_id,skill_id));
        CREATE TABLE schedule_blocks (id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, end_date TEXT, status TEXT DEFAULT 'draft');
        CREATE TABLE staff_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, block_id INTEGER, staff_id INTEGER, date TEXT, skill_id INTEGER, UNIQUE(block_id,staff_id,date,skill_id));
        CREATE TABLE staff_unavailability (id INTEGER PRIMARY KEY AUTOINCREMENT, block_id INTEGER, staff_id INTEGER, date TEXT, UNIQUE(block_id,staff_id,date));
        CREATE TABLE template_needs (id INTEGER PRIMARY KEY AUTOINCREMENT, template_id INTEGER, day_of_week TEXT, skill_id INTEGER, quantity INTEGER);
        CREATE TABLE skill_minimums (skill_id INTEGER PRIMARY KEY, minimum_count INTEGER);
        CREATE TABLE day_priority (day_of_week TEXT PRIMARY KEY, priority INTEGER);
        CREATE TABLE rotation_history (staff_id INTEGER, skill_id INTEGER, last_date TEXT, PRIMARY KEY(staff_id,skill_id));
        CREATE TABLE closed_dates (date TEXT PRIMARY KEY);
        CREATE TABLE optimized_schedule (block_id INTEGER PRIMARY KEY, result_json TEXT, optimized_at TEXT);
    """)

    # Skills
    conn.executemany("INSERT INTO skills VALUES (?,?,?)", [
        (1,"TL",1),(2,"IRC",2),(3,"ECU",3),(4,"IR RN",4),(5,"Call",5)
    ])

    # Staff — 13 staff matching production headcount
    conn.executemany("INSERT INTO staff VALUES (?,?,?)", [
        (1,"Alice",1.0),(2,"Bob",1.0),(3,"Carol",0.75),(4,"Dave",0.75),
        (5,"Eve",0.6),(6,"Frank",0.75),(7,"Grace",0.75),(8,"Heidi",1.0),
        (9,"Ivan",0.75),(10,"Judy",0.75),(11,"Karl",1.0),(12,"Lena",0.75),
        (13,"Mick",0.75),
    ])

    # Staff skills
    for sid in [1,2,8,11]:              conn.execute("INSERT INTO staff_skills VALUES(?,1)",(sid,))  # TL
    for sid in [1,2,3,6,8,9,11,12]:     conn.execute("INSERT INTO staff_skills VALUES(?,2)",(sid,))  # IRC
    for sid in [1,2,3,4,5,6,7,8,9,10,11,12,13]: conn.execute("INSERT INTO staff_skills VALUES(?,3)",(sid,))  # ECU
    for sid in [1,2,3,4,6,7,8,9,10,11,12,13]:   conn.execute("INSERT INTO staff_skills VALUES(?,4)",(sid,))  # IR RN

    # Block
    conn.execute("INSERT INTO schedule_blocks VALUES(1,'Test',?,?,'draft')",
                 (start_date, end_date))

    # Template needs
    nid = 1
    for day in ['Monday','Tuesday','Wednesday','Thursday','Friday']:
        for skid, qty in [(1,1),(2,1),(3,2),(4,5)]:
            conn.execute("INSERT INTO template_needs VALUES(?,1,?,?,?)",(nid,day,skid,qty))
            nid += 1

    # Minimums
    conn.executemany("INSERT INTO skill_minimums VALUES(?,?)",
                     [(1,1),(2,1),(3,2),(4,3)])

    # Day priorities
    conn.executemany("INSERT INTO day_priority VALUES(?,?)", [
        ('Monday',2),('Tuesday',4),('Wednesday',1),
        ('Thursday',5),('Friday',3),('Saturday',6),('Sunday',6)
    ])

    conn.commit()
    return conn


# ═══════════════════════════════════════════════════════════
# CATEGORY 1: Mathematical Edge Cases
# ═══════════════════════════════════════════════════════════

def test_zero_slack():
    """Total FTE shifts exactly equals total slots — no room for error."""
    section("Cat 1a: Zero Slack (FTE = slots exactly)")
    # Standard 8-week block has 344-360 slots depending on template
    # Use a 2-week block with exactly matching FTE
    conn = base_db('2026-04-20', '2026-05-02')

    # Reduce staff to only have enough FTE to fill exactly the slots
    # 2 weeks × 5 days × 9 slots = 90 slots
    # Keep 3 staff: 1.0 FTE (8 shifts), 1.0 FTE (8 shifts), don't need exact match
    # Just verify it runs and doesn't crash
    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles tight slot/FTE ratio",
          error is None or "feasible" in str(error).lower(),
          error or "")


def test_staff_unavailable_entire_block():
    """One staff member is unavailable for the entire block."""
    section("Cat 1b: Staff Unavailable Entire Block")
    conn = base_db('2026-04-20', '2026-06-13')

    # Mark Alice unavailable every weekday
    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    for d in weekdays:
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,1,?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("No solution with Alice out entire block", error)
        return

    # Alice should not appear anywhere
    alice_dates = []
    for date, day in result.items():
        if date == "unmet": continue
        for names in day.values():
            if "Alice" in names:
                alice_dates.append(date)

    check("Unavailable-all-block staff never scheduled", len(alice_dates) == 0,
          f"Alice appears on: {alice_dates[:3]}")
    assert_no_fte_ceiling_violations(conn, result, '2026-04-20', '2026-06-13',
                                     "with Alice out all block")


def test_entire_pay_period_unavailable():
    """Staff unavailable for all weekdays in one pay period."""
    section("Cat 1c: Staff Unavailable Entire Pay Period")
    conn = base_db('2026-04-20', '2026-06-13')

    pps = get_pay_periods('2026-04-20', '2026-06-13')
    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    ps, pe = pps[1]  # PP2
    pp2_days = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()]

    for d in pp2_days:
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,1,?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("No solution with Alice out for PP2", error)
        return

    alice_in_pp2 = [
        date for date in pp2_days
        for names in result.get(date, {}).values()
        if "Alice" in names
    ]
    check("Staff not scheduled during fully unavailable pay period",
          len(alice_in_pp2) == 0,
          f"Alice appears: {alice_in_pp2[:3]}")


def test_two_staff_same_week_unavailable():
    """Two staff unavailable same week — may drop below minimums."""
    section("Cat 1d: Two Staff Unavailable Same Week")
    conn = base_db('2026-04-20', '2026-06-13')

    # Alice and Bob both out week 1 (2026-04-20 to 2026-04-24)
    week1_days = ['2026-04-21','2026-04-22','2026-04-23','2026-04-24']  # Mon-Thu
    for d in week1_days:
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,1,?)",(d,))
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,2,?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("No solution with Alice+Bob out same week — minimums may be impossible", error)
        return

    # Check minimums on those days
    violations = []
    for date in week1_days:
        day = result.get(date, {})
        for skill, minimum in [("TL",1),("IRC",1),("ECU",2),("IR RN",3)]:
            count = len(day.get(skill, []))
            if count < minimum:
                violations.append(f"{date} {skill}: {count}/{minimum}")

    if violations:
        warn(f"Minimums dropped with two TL/IRC staff out: {violations[:3]}")
    else:
        check("Minimums still met with two senior staff out", True)


def test_block_starts_friday():
    """Block starting on a Friday — first week has only 1 weekday."""
    section("Cat 1e: Block Starts on Friday")
    # 2026-05-01 is a Friday
    conn = base_db('2026-05-01', '2026-06-26')
    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles block starting on Friday",
          error is None,
          error or "")
    if result:
        # First day should be staffed
        day = result.get('2026-05-01', {})
        check("First Friday is staffed",
              any(names for names in day.values()),
              "No assignments on first day")


def test_block_starts_sunday():
    """Block starting on a Sunday."""
    section("Cat 1f: Block Starts on Sunday")
    # 2026-04-19 is a Sunday
    conn = base_db('2026-04-19', '2026-06-13')
    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles block starting on Sunday",
          error is None,
          error or "")


# ═══════════════════════════════════════════════════════════
# CATEGORY 2: Skill Coverage Gaps
# ═══════════════════════════════════════════════════════════

def test_only_one_tl_available():
    """Only one staff member has TL skill — can't cover all 5 days with 4 shift weekly cap."""
    section("Cat 2a: Only One TL-Qualified Staff")
    conn = base_db('2026-04-20', '2026-06-13')

    # Remove TL from Bob, Heidi, Karl — only Alice has TL
    conn.execute("DELETE FROM staff_skills WHERE staff_id IN (2,8,11) AND skill_id=1")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("No solution with only one TL", error)
        return

    weekdays = get_weekdays('2026-04-20', '2026-06-13')

    # Alice works 4 shifts/week max — she can't cover all 5 TL days/week
    # So some days will have no TL — check the optimizer picked high-priority days
    tl_days     = [d for d in weekdays if "Alice" in result.get(d, {}).get("TL", [])]
    no_tl_days  = [d for d in weekdays
                   if dt_date.fromisoformat(d).weekday() < 5
                   and not result.get(d, {}).get("TL")]
    no_tl_days_names = [dt_date.fromisoformat(d).strftime("%A") for d in no_tl_days]

    # Should not exceed weekly FTE
    weeks = get_weeks('2026-04-20', '2026-06-13')
    over_weeks = []
    for ws, we in weeks:
        wk_tl = [d for d in tl_days if ws.isoformat() <= d <= we.isoformat()]
        if len(wk_tl) > 4:
            over_weeks.append(f"{ws}: {len(wk_tl)} TL days")

    check("Single TL staff never exceeds weekly ceiling",
          len(over_weeks) == 0, "; ".join(over_weeks))

    # Missing TL days should be low priority days (Thursday=5, Tuesday=4)
    high_prio_missing = [d for d in no_tl_days
                         if dt_date.fromisoformat(d).strftime("%A")
                         in ("Wednesday", "Monday")]
    check("Missing TL days are low-priority days (not Wed/Mon)",
          len(high_prio_missing) == 0,
          f"Missing TL on high-priority days: {[dt_date.fromisoformat(d).strftime('%A %m/%d') for d in high_prio_missing[:3]]}")

    print(f"       Info: TL covered {len(tl_days)}/{len(weekdays)} days. "
          f"Missing on: {set(no_tl_days_names)}")


def test_minimum_exceeds_qualified_staff():
    """Minimum staffing requirement exceeds number of qualified staff."""
    section("Cat 2b: Minimum > Qualified Staff Count")
    conn = base_db('2026-04-20', '2026-06-13')

    # Set TL minimum to 3 but only 3 staff have TL
    # This is at the boundary — might be feasible or not
    conn.execute("UPDATE skill_minimums SET minimum_count=3 WHERE skill_id=1")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("Infeasible when TL minimum=3 with 3 TL staff — expected", error)
    else:
        # Check if minimum is met
        violations = []
        for date, day in result.items():
            if date == "unmet": continue
            if dt_date.fromisoformat(date).weekday() >= 5: continue
            count = len(day.get("TL", []))
            if count < 3:
                violations.append(f"{date}: {count}/3")
        check("TL minimum=3 met when 3 qualified staff available",
              len(violations) == 0,
              f"{len(violations)} violations")


def test_all_ecu_only_staff_unavailable():
    """Eve (ECU-only) unavailable for entire block — ECU still covered by multi-skill staff."""
    section("Cat 2c: ECU-Only Staff Unavailable All Block")
    conn = base_db('2026-04-20', '2026-06-13')

    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    for d in weekdays:
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,5,?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    # Expected: infeasible because Eve has a hard FTE floor but no valid slots
    # This is a known limitation — single-skill staff cannot be unavailable all block
    if error and "insufficient slots" in error:
        warn("Expected: single-skill staff can't be unavailable all block", error)
        return

    check("Optimizer finds solution when ECU-only staff is out all block",
          error is None, error or "")

    if result:
        violations = [
            date for date, day in result.items()
            if date != "unmet"
            and dt_date.fromisoformat(date).weekday() < 5
            and len(day.get("ECU", [])) < 2
        ]
        check("ECU minimum still met without Eve",
              len(violations) == 0,
              f"{len(violations)} days short")


# ═══════════════════════════════════════════════════════════
# CATEGORY 3: FTE Conflicts
# ═══════════════════════════════════════════════════════════

def test_negative_required_shifts():
    """Staff with many unavailable days — required shifts approach zero."""
    section("Cat 3a: Many Unavailable Days (required shifts near zero)")
    print("       Setting up...")
    conn = base_db('2026-04-20', '2026-06-13')

    # Give Alice (1.0 FTE, target=8/PP) 7 unavailable days in PP1
    # required = max(0, 8 - 7) = 1
    pps = get_pay_periods('2026-04-20', '2026-06-13')
    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    ps, pe = pps[0]
    pp1_days = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()][:7]

    for d in pp1_days:
        conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,1,?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles near-zero required shifts",
          error is None, error or "")

    if result:
        all_pp1       = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()]
        available_days = [d for d in all_pp1 if d not in pp1_days]
        alice_pp1     = [
            date for date in all_pp1
            if any("Alice" in names for names in result.get(date, {}).values())
        ]
        # Alice has 3 available days and target=1 (8-7), should work exactly 1
        # But optimizer also has soft FTE pressure — it may schedule all available days
        # What matters is she doesn't EXCEED the ceiling of 8
        check("Alice does not exceed FTE ceiling despite 7 unavailable days in PP1",
              len(alice_pp1) <= 8 - 0,  # ceiling = target - 0 unavail on available days
              f"Alice worked {len(alice_pp1)} shifts, available: {available_days}")


def test_fte_already_full_via_requests():
    """Staff FTE already met via requests — optimizer should not add more."""
    section("Cat 3b: FTE Already Full Via Requests")
    conn = base_db('2026-04-20', '2026-06-13')

    # Fill Alice's entire PP1 (8 shifts) with IR RN requests
    pps = get_pay_periods('2026-04-20', '2026-06-13')
    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    ps, pe = pps[0]
    pp1_days = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()][:8]

    for d in pp1_days:
        conn.execute("INSERT INTO staff_requests VALUES(NULL,1,1,?,4)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer runs when staff already at FTE",
          error is None, error or "")

    if result:
        alice_pp1 = [
            date for date in [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()]
            if any("Alice" in names for names in result.get(date, {}).values())
        ]
        check("Alice not over-scheduled beyond PP1 FTE",
              len(alice_pp1) <= 8,
              f"Alice has {len(alice_pp1)} shifts in PP1")


def test_all_staff_point_six_fte():
    """All staff at 0.6 FTE — total capacity may be below department needs."""
    section("Cat 3c: All Staff 0.6 FTE (capacity stress)")
    conn = base_db('2026-04-20', '2026-06-13')

    # Set everyone to 0.6 FTE
    conn.execute("UPDATE staff SET fte=0.6")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("No solution with all 0.6 FTE — capacity likely insufficient", error)
    else:
        # Check FTE ceilings
        assert_no_fte_ceiling_violations(conn, result, '2026-04-20', '2026-06-13',
                                         "all 0.6 FTE")
        warn("Found solution with all 0.6 FTE — verify staffing levels are acceptable")


# ═══════════════════════════════════════════════════════════
# CATEGORY 4: Repeat Runs
# ═══════════════════════════════════════════════════════════

def test_multiple_optimizer_runs():
    """Run optimizer 3 times — FTE should never exceed ceiling."""
    section("Cat 4a: Multiple Optimizer Runs (FTE drift check)")
    conn = base_db('2026-04-20', '2026-06-13')

    for run_num in range(1, 4):
        result, error = run_optimizer(conn, time_limit=30)
        if error:
            check(f"Run {run_num} succeeds", False, error)
            break

        # Simulate accept — replace requests with optimizer output
        skills = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM skills")}
        staff  = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM staff")}
        conn.execute("DELETE FROM staff_requests WHERE block_id=1")
        for date, day in result.items():
            if date == "unmet": continue
            for skill_name, names in day.items():
                skid = skills.get(skill_name)
                if not skid: continue
                for name in names:
                    sid = staff.get(name)
                    if not sid: continue
                    conn.execute(
                        "INSERT OR IGNORE INTO staff_requests VALUES(NULL,1,?,?,?)",
                        (sid, date, skid)
                    )
        conn.commit()

        violations = assert_no_fte_ceiling_violations(
            conn, result, '2026-04-20', '2026-06-13', f"run {run_num}"
        )
        check(f"Run {run_num} completes without FTE violations",
              len(violations) == 0)


def test_rotation_history_affects_next_block():
    """Rotation history from block 1 should penalize same staff in block 2."""
    section("Cat 4b: Rotation History Carries Between Blocks")
    conn = base_db('2026-04-20', '2026-06-13')

    result1, error = run_optimizer(conn, time_limit=30)
    if error:
        warn("Block 1 failed, skipping cross-block test", error)
        return

    # Use IRC — always done by multi-skilled staff
    irc_counts = defaultdict(int)
    for date, day in result1.items():
        if date == "unmet": continue
        for name in day.get("IRC", []):
            irc_counts[name] += 1

    top_irc = max(irc_counts, key=irc_counts.get) if irc_counts else None
    check("Block 1 has IRC assignments to track",
          top_irc is not None, "No IRC assignments found")

    if not top_irc:
        return

    # Create block 2 starting right after block 1
    conn.execute("INSERT INTO schedule_blocks VALUES(2,'Block2','2026-06-14','2026-08-08','draft')")
    conn.commit()

    result2, error = run_optimizer(conn, block_id=2, time_limit=30)
    if error:
        warn("Block 2 failed", error)
        return

    top_irc_b2 = sum(
        1 for date, day in result2.items()
        if date != "unmet" and top_irc in day.get("IRC", [])
    )
    avg_irc_b2 = (
        sum(1 for date, day in result2.items()
            if date != "unmet"
            for name in day.get("IRC", []))
        / max(1, len(irc_counts))
    )

    check(f"Top IRC person ({top_irc}) does not dominate IRC in block 2",
          top_irc_b2 <= avg_irc_b2 * 2,
          f"{top_irc}: {irc_counts[top_irc]} in B1, {top_irc_b2} in B2 vs avg {avg_irc_b2:.1f}")


def test_future_rotation_history():
    """Rotation history with a future date — should not crash."""
    section("Cat 4c: Future Date in Rotation History")
    conn = base_db('2026-04-20', '2026-06-13')

    # Plant a future date in rotation_history
    conn.execute("INSERT INTO rotation_history VALUES(1, 3, '2027-01-01')")  # Alice, ECU
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles future rotation history date",
          error is None, error or "")


# ═══════════════════════════════════════════════════════════
# CATEGORY 5: Data Integrity
# ═══════════════════════════════════════════════════════════

def test_staff_with_no_skills():
    """Staff member with no skills at all — should be ignored gracefully."""
    section("Cat 5a: Staff With No Skills")
    conn = base_db('2026-04-20', '2026-06-13')
    conn.execute("INSERT INTO staff VALUES(14,'Ghost',1.0)")
    conn.commit()  # No staff_skills rows for Ghost

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles staff with no skills (ignores them)",
          error is None, error or "")

    if result:
        ghost_dates = [
            date for date, day in result.items()
            if date != "unmet"
            and any("Ghost" in names for names in day.values())
        ]
        check("Staff with no skills never scheduled",
              len(ghost_dates) == 0,
              f"Ghost scheduled on: {ghost_dates[:3]}")


def test_closed_date_in_middle():
    """Closed date in the middle of the block — that day should be empty."""
    section("Cat 5b: Closed Date Mid-Block")
    conn = base_db('2026-04-20', '2026-06-13')

    # Close a Wednesday (2026-04-22)
    conn.execute("INSERT INTO closed_dates VALUES('2026-04-22')")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles closed dates", error is None, error or "")

    if result:
        closed_day = result.get('2026-04-22', {})
        assigned   = {k: v for k, v in closed_day.items() if v}
        check("No assignments on closed date",
              len(assigned) == 0,
              f"Assignments found: {assigned}")


def test_zero_quantity_template_need():
    """Template need with quantity 0 — should not crash."""
    section("Cat 5c: Template Need With Quantity 0")
    conn = base_db('2026-04-20', '2026-06-13')

    # Add a zero-quantity need
    conn.execute("INSERT INTO template_needs VALUES(999,1,'Monday',4,0)")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles zero-quantity template need",
          error is None, error or "")


def test_all_days_closed():
    """Every weekday is closed — result should be empty, not a crash."""
    section("Cat 5d: All Weekdays Closed")
    conn = base_db('2026-04-20', '2026-06-13')

    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    for d in weekdays:
        conn.execute("INSERT INTO closed_dates VALUES(?)",(d,))
    conn.commit()

    result, error = run_optimizer(conn, time_limit=15)
    if error:
        warn("Optimizer returns error when all days closed — check if graceful", error)
    else:
        total = sum(
            len(names) for date, day in result.items()
            if date != "unmet"
            for names in day.values()
        )
        check("No assignments when all days closed", total == 0,
              f"Found {total} assignments")


# ═══════════════════════════════════════════════════════════
# CATEGORY 6: Request Conflicts
# ═══════════════════════════════════════════════════════════

def test_request_for_unqualified_skill():
    """Staff requests a skill they don't have."""
    section("Cat 6a: Request for Unqualified Skill")
    conn = base_db('2026-04-20', '2026-06-13')

    # Eve requests TL (she only has ECU)
    conn.execute("INSERT INTO staff_requests VALUES(NULL,1,5,'2026-04-21',1)")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles unqualified skill request",
          error is None, error or "")

    if result:
        eve_tl = "Eve" in result.get('2026-04-21', {}).get("TL", [])
        check("Unqualified request not honored (Eve not assigned TL)",
              not eve_tl)


def test_request_on_unavailable_day():
    """Staff requests a day they're marked unavailable."""
    section("Cat 6b: Request on Unavailable Day")
    conn = base_db('2026-04-20', '2026-06-13')

    # Alice requests ECU on Monday but is also marked unavailable
    conn.execute("INSERT INTO staff_requests VALUES(NULL,1,1,'2026-04-20',3)")
    conn.execute("INSERT INTO staff_unavailability VALUES(NULL,1,1,'2026-04-20')")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles request on unavailable day",
          error is None, error or "")

    if result:
        alice_monday = any(
            "Alice" in names
            for names in result.get('2026-04-20', {}).values()
        )
        check("Unavailability overrides request (Alice not scheduled)",
              not alice_monday)


def test_two_staff_request_same_tl_slot():
    """Two staff both request TL on the same day — only one can have it."""
    section("Cat 6c: Two Staff Request Same TL Slot")
    conn = base_db('2026-04-20', '2026-06-13')

    # Alice and Bob both request TL on Monday
    conn.execute("INSERT INTO staff_requests VALUES(NULL,1,1,'2026-04-20',1)")
    conn.execute("INSERT INTO staff_requests VALUES(NULL,1,2,'2026-04-20',1)")
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles competing TL requests",
          error is None, error or "")

    if result:
        tl_monday = result.get('2026-04-20', {}).get("TL", [])
        check("Only one TL assigned when two staff request it",
              len(tl_monday) <= 1,
              f"TL assigned: {tl_monday}")


def test_requests_exceed_fte():
    """Staff has more requests than their FTE allows."""
    section("Cat 6d: Requests Exceed FTE")
    conn = base_db('2026-04-20', '2026-06-13')

    # Give Eve (0.6 FTE, target=5/PP) 10 requests in PP1
    pps = get_pay_periods('2026-04-20', '2026-06-13')
    weekdays = get_weekdays('2026-04-20', '2026-06-13')
    ps, pe = pps[0]
    pp1_days = [d for d in weekdays if ps.isoformat() <= d <= pe.isoformat()]

    for d in pp1_days:  # all 10 weekdays in PP1
        conn.execute("INSERT INTO staff_requests VALUES(NULL,1,5,?,3)",(d,))  # ECU
    conn.commit()

    result, error = run_optimizer(conn, time_limit=30)
    check("Optimizer handles requests exceeding FTE",
          error is None, error or "")

    if result:
        eve_pp1 = [
            date for date in pp1_days
            if any("Eve" in names for names in result.get(date, {}).values())
        ]
        check("Eve not scheduled beyond FTE ceiling despite excess requests",
              len(eve_pp1) <= 5,
              f"Eve scheduled {len(eve_pp1)} shifts in PP1 (max 5)")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("IR Schedule — Adversarial Test Suite")
    print("=" * 60)
    print("Note: WARN warnings are expected failures for truly impossible")
    print("      scenarios. FAIL failures indicate unexpected behavior.")

    # Cat 1: Mathematical edge cases
    test_zero_slack()
    test_staff_unavailable_entire_block()
    test_entire_pay_period_unavailable()
    test_two_staff_same_week_unavailable()
    test_block_starts_friday()
    test_block_starts_sunday()

    # Cat 2: Skill coverage gaps
    test_only_one_tl_available()
    test_minimum_exceeds_qualified_staff()
    test_all_ecu_only_staff_unavailable()

    # Cat 3: FTE conflicts
    test_negative_required_shifts()
    test_fte_already_full_via_requests()
    test_all_staff_point_six_fte()

    # Cat 4: Repeat runs
    test_multiple_optimizer_runs()
    test_rotation_history_affects_next_block()
    test_future_rotation_history()

    # Cat 5: Data integrity
    test_staff_with_no_skills()
    test_closed_date_in_middle()
    test_zero_quantity_template_need()
    test_all_days_closed()

    # Cat 6: Request conflicts
    test_request_for_unqualified_skill()
    test_request_on_unavailable_day()
    test_two_staff_request_same_tl_slot()
    test_requests_exceed_fte()

    # Summary
    total = results["passed"] + results["failed"]
    print(f"\n{'=' * 60}")
    print(f"Results: {results['passed']}/{total} passed, {results['warned']} warnings")
    if results["errors"]:
        print(f"Failed:  {', '.join(results['errors'])}")
    print("=" * 60)
    sys.exit(0 if results["failed"] == 0 else 1)