"""
optimizer.py
------------
OR-Tools CP-SAT optimizer for IR Schedule.

Workflow:
  1. Staff enter requests (date + skill) via the block grid
  2. Admin enters unavailability
  3. This optimizer takes requests as the preferred solution and
     adjusts minimally to satisfy all constraints
  4. Result is stored in optimized_schedule table per block

Decision variable:
  x[staff_id, date, skill_id] ∈ {0, 1}
  = 1 if that staff member works that skill on that date

Hard constraints:
  - Unavailable staff cannot be assigned on that date
  - Staff must have the skill (except Call — anyone can take call)
  - One skill per staff per day
  - TL assigned on a day → that staff cannot fill any other skill that day
  - FTE: shifts per pay period (Mon–Fri only) must not exceed FTE target
  - Bare minimums per day must be met if at all possible (penalized if not)
  - Closed dates and weekends (except Call) are skipped

Soft constraints (objective — minimize):
  TIER 1 (weight 1000): understaffing below bare minimums
  TIER 2 (weight 100):  understaffing below template targets
  TIER 3 (weight 10):   moves away from staff requests (wrong day or wrong skill)
  TIER 4 (weight 1):    IRC/ECU rotation imbalance

Rotation skills (IRC, ECU):
  Pre-computed penalty per staff member based on rotation_history.last_date.
  Staff who did it most recently get higher penalty — solver avoids reassigning them.
"""

import sqlite3
from datetime import date as dt_date, timedelta
from ortools.sat.python import cp_model

DATABASE = "ir_schedule.db"

# Rotation skill names
ROTATION_SKILLS = {"IRC", "ECU"}

# Skill that is allowed on weekends
WEEKEND_SKILL = "Call"

# TL skill name
TL_SKILL = "TL"

# Objective weights
W_MINIMUM    = 1000   # penalty per unfilled minimum slot
W_TARGET     = 100    # penalty per unfilled target slot above minimum
W_MOVE       = 10     # penalty per request not honored
W_ROTATION   = 1      # penalty for assigning rotation skill to recent assignee


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(conn, block_id):
    block = conn.execute(
        "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if not block:
        raise ValueError(f"Block {block_id} not found")

    # Staff
    staff_rows = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
    staff = {}
    for s in staff_rows:
        skill_ids = set(
            r["skill_id"] for r in conn.execute(
                "SELECT skill_id FROM staff_skills WHERE staff_id = ?", (s["id"],)
            ).fetchall()
        )
        staff[s["id"]] = {
            "id":       s["id"],
            "name":     s["name"],
            "fte":      s["fte"],
            "skill_ids": skill_ids,
        }

    # Skills
    skill_rows = conn.execute(
        "SELECT * FROM skills ORDER BY CASE WHEN priority=0 THEN 999 ELSE priority END, name"
    ).fetchall()
    skills = {s["id"]: dict(s) for s in skill_rows}

    # Template needs: {day_name: {skill_id: quantity}}
    need_rows = conn.execute("""
        SELECT day_of_week, skill_id, quantity
        FROM template_needs WHERE template_id = 1
    """).fetchall()
    template_needs = {}
    for r in need_rows:
        template_needs.setdefault(r["day_of_week"], {})[r["skill_id"]] = r["quantity"]

    # Skill minimums
    min_rows = conn.execute("SELECT skill_id, minimum_count FROM skill_minimums").fetchall()
    skill_minimums = {r["skill_id"]: r["minimum_count"] for r in min_rows}

    # Staff requests: {(staff_id, date, skill_id)}
    req_rows = conn.execute(
        "SELECT staff_id, date, skill_id FROM staff_requests WHERE block_id = ?", (block_id,)
    ).fetchall()
    requests = {(r["staff_id"], r["date"], r["skill_id"]) for r in req_rows}

    # Unavailability: {staff_id: {date}}
    unavail_rows = conn.execute(
        "SELECT staff_id, date FROM staff_unavailability WHERE block_id = ?", (block_id,)
    ).fetchall()
    unavailability = {}
    for u in unavail_rows:
        unavailability.setdefault(u["staff_id"], set()).add(u["date"])

    # Closed dates
    closed = set(
        r["date"] for r in conn.execute("SELECT date FROM closed_dates").fetchall()
    )

    # Rotation history: {(staff_id, skill_id): last_date_str}
    rot_rows = conn.execute(
        "SELECT staff_id, skill_id, last_date FROM rotation_history"
    ).fetchall()
    rotation_history = {(r["staff_id"], r["skill_id"]): r["last_date"] for r in rot_rows}

    return block, staff, skills, template_needs, skill_minimums, requests, unavailability, closed, rotation_history


def _build_dates(block):
    """Return all Mon–Fri dates in the block, plus all dates for Call (7 days)."""
    start = dt_date.fromisoformat(block["start_date"])
    end   = dt_date.fromisoformat(block["end_date"])
    all_dates     = []
    weekday_dates = []
    d = start
    while d <= end:
        all_dates.append(d.isoformat())
        if d.weekday() < 5:
            weekday_dates.append(d.isoformat())
        d += timedelta(days=1)
    return all_dates, weekday_dates


def _pay_periods(block):
    start     = dt_date.fromisoformat(block["start_date"])
    end       = dt_date.fromisoformat(block["end_date"])
    days_back = (start.weekday() + 1) % 7
    p_start   = start - timedelta(days=days_back)
    periods   = []
    while p_start <= end:
        p_end = p_start + timedelta(days=13)
        periods.append((p_start, p_end))
        p_start = p_end + timedelta(days=1)
    return periods


def _fte_target(fte):
    if fte >= 1.0:  return 8
    if fte >= 0.75: return 6
    return 5


def _rotation_penalty(staff_id, skill_id, rotation_history, all_dates):
    """
    Return a penalty weight for assigning staff_id to a rotation skill.
    Higher = assigned more recently = solver avoids them.
    Staff with no history get penalty 0 (preferred for rotation).
    """
    key = (staff_id, skill_id)
    if key not in rotation_history:
        return 0
    last = rotation_history[key]
    # Count how many block dates have passed since last assignment
    # The further back, the lower the penalty
    days_ago = (dt_date.fromisoformat(all_dates[-1]) -
                dt_date.fromisoformat(last)).days
    # Penalty inversely proportional to days ago — cap at 100
    return max(0, 100 - days_ago)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def optimize(conn, block_id, time_limit_seconds=30):
    """
    Run the CP-SAT optimizer for the given block.
    Returns result dict: {date: {skill_name: [staff_name, ...]}, "unmet": {...}}
    """
    (block, staff, skills, template_needs, skill_minimums,
     requests, unavailability, closed, rotation_history) = _load(conn, block_id)

    all_dates, weekday_dates = _build_dates(block)
    pay_periods = _pay_periods(block)

    staff_ids = list(staff.keys())
    skill_ids = list(skills.keys())

    # Skill name lookups
    skill_name = {sid: skills[sid]["name"] for sid in skill_ids}
    call_skill_ids     = [sid for sid in skill_ids if skill_name[sid] == WEEKEND_SKILL]
    tl_skill_ids       = [sid for sid in skill_ids if skill_name[sid] == TL_SKILL]
    rotation_skill_ids = [sid for sid in skill_ids if skill_name[sid] in ROTATION_SKILLS]
    call_skill_id      = call_skill_ids[0] if call_skill_ids else None
    tl_skill_id        = tl_skill_ids[0]   if tl_skill_ids   else None

    # Skills the optimizer is allowed to assign (exclude Call — managed manually)
    optimizer_skill_ids = [sid for sid in skill_ids if skill_name[sid] != WEEKEND_SKILL]

    model = cp_model.CpModel()

    # ── Decision variables ───────────────────────────────────────────────────
    # x[staff_id][date][skill_id] = BoolVar
    # Call is excluded — managed manually
    x = {}
    for sid in staff_ids:
        x[sid] = {}
        for date in all_dates:
            x[sid][date] = {}
            is_weekend = dt_date.fromisoformat(date).weekday() >= 5
            for skid in optimizer_skill_ids:
                # Weekends: no regular skills (Call excluded from optimizer)
                if is_weekend:
                    x[sid][date][skid] = model.NewConstant(0)
                    continue
                # Closed date
                if date in closed:
                    x[sid][date][skid] = model.NewConstant(0)
                    continue
                # Unavailable
                if date in unavailability.get(sid, set()):
                    x[sid][date][skid] = model.NewConstant(0)
                    continue
                # Staff doesn't have this skill
                if skid not in staff[sid]["skill_ids"]:
                    x[sid][date][skid] = model.NewConstant(0)
                    continue
                x[sid][date][skid] = model.NewBoolVar(f"x_{sid}_{date}_{skid}")

    # ── Hard constraints ─────────────────────────────────────────────────────

    # 1. One skill per staff per day
    for sid in staff_ids:
        for date in all_dates:
            model.AddAtMostOne(
                x[sid][date][skid] for skid in optimizer_skill_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            )

    # 2. TL assigned → cannot fill any other role that day
    if tl_skill_id:
        for sid in staff_ids:
            if tl_skill_id not in staff[sid]["skill_ids"]:
                continue
            for date in weekday_dates:
                tl_var = x[sid][date][tl_skill_id]
                if not isinstance(tl_var, cp_model.IntVar):
                    continue
                for skid in optimizer_skill_ids:
                    if skid == tl_skill_id:
                        continue
                    other_var = x[sid][date][skid]
                    if not isinstance(other_var, cp_model.IntVar):
                        continue
                    # If TL = 1, other must = 0
                    model.Add(other_var == 0).OnlyEnforceIf(tl_var)

    # 3. FTE cap per pay period (Mon–Fri only, Call on weekends not counted)
    # 3. FTE is both floor and ceiling per pay period
    #    shifts_worked + unavailable_days = FTE target
    #    So: shifts_worked = target - unavailable_days
    #    If unavailable_days >= target, staff works 0 shifts that period
    for sid in staff_ids:
        target = _fte_target(staff[sid]["fte"])
        unavail_dates = unavailability.get(sid, set())

        for p_start, p_end in pay_periods:
            period_weekday_dates = [
                d for d in weekday_dates
                if p_start.isoformat() <= d <= p_end.isoformat()
            ]

            # Count unavailable weekdays in this period
            unavail_count = sum(
                1 for d in period_weekday_dates if d in unavail_dates
            )

            # Required shifts = target minus days unavailable (min 0)
            required = max(0, target - unavail_count)

            period_vars = []
            for date in period_weekday_dates:
                if date in unavail_dates:
                    continue
                for skid in optimizer_skill_ids:
                    v = x[sid][date][skid]
                    if isinstance(v, cp_model.IntVar):
                        period_vars.append(v)

            if period_vars:
                model.Add(sum(period_vars) == required)

    # ── Penalty variables ────────────────────────────────────────────────────
    penalties = []

    # 4. Bare minimums (TIER 1 — heavy penalty if unmet)
    unmet_min_vars = {}
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})
        for skid, qty in day_needs.items():
            minimum = skill_minimums.get(skid, 0)
            if minimum == 0:
                continue
            # Sum of assignments for this skill on this date
            if skid not in optimizer_skill_ids:
                continue
            assigned = [
                x[sid][date][skid] for sid in staff_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if not assigned:
                continue
            # Slack = how many below minimum (capped at minimum)
            slack = model.NewIntVar(0, minimum, f"slack_min_{date}_{skid}")
            model.Add(slack == minimum - sum(assigned)).OnlyEnforceIf(
                model.NewBoolVar(f"below_min_{date}_{skid}")
            )
            # Simpler: penalty = max(0, minimum - sum)
            shortage = model.NewIntVar(0, minimum, f"shortage_min_{date}_{skid}")
            model.Add(shortage >= minimum - sum(assigned))
            model.Add(shortage >= 0)
            penalties.append(W_MINIMUM * shortage)
            unmet_min_vars[(date, skid)] = shortage

    # 5. Template targets above minimums (TIER 2)
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})
        for skid, qty in day_needs.items():
            minimum = skill_minimums.get(skid, 0)
            if qty <= minimum:
                continue
            if skid not in optimizer_skill_ids:
                continue
            assigned = [
                x[sid][date][skid] for sid in staff_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if not assigned:
                continue
            shortage = model.NewIntVar(0, qty - minimum, f"shortage_tgt_{date}_{skid}")
            model.Add(shortage >= qty - sum(assigned))
            model.Add(shortage >= 0)
            penalties.append(W_TARGET * shortage)

    # 6. Moves away from requests (TIER 3)
    # For each request (sid, date, skid), penalize if not assigned
    for (sid, date, skid) in requests:
        if sid not in staff or skid not in skills:
            continue
        v = x.get(sid, {}).get(date, {}).get(skid)
        if v is None or not isinstance(v, cp_model.IntVar):
            continue
        not_honored = model.NewBoolVar(f"move_{sid}_{date}_{skid}")
        model.Add(not_honored == 1 - v)
        penalties.append(W_MOVE * not_honored)

    # 7. Rotation fairness (TIER 4)
    for skid in rotation_skill_ids:
        for sid in staff_ids:
            if skid not in staff[sid]["skill_ids"]:
                continue
            penalty_weight = _rotation_penalty(sid, skid, rotation_history, weekday_dates)
            if penalty_weight == 0:
                continue
            for date in weekday_dates:
                v = x[sid][date].get(skid)
                if isinstance(v, cp_model.IntVar):
                    penalties.append(penalty_weight * W_ROTATION * v)

    # ── Objective ────────────────────────────────────────────────────────────
    model.Minimize(sum(penalties) if penalties else model.NewConstant(0))

    # ── Solve ────────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers  = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, "No feasible solution found. Check constraints and staff coverage."

    # ── Extract result ────────────────────────────────────────────────────────
    result = {}
    unmet  = {}

    for date in all_dates:
        result[date] = {}
        unmet[date]  = {}
        is_weekend = dt_date.fromisoformat(date).weekday() >= 5

        for skid in optimizer_skill_ids:
            sname    = skill_name[skid]
            assigned_names = []
            for sid in staff_ids:
                v = x[sid][date][skid]
                val = solver.Value(v) if isinstance(v, cp_model.IntVar) else int(v)
                if val == 1:
                    assigned_names.append(staff[sid]["name"])
            if assigned_names:
                result[date][sname] = assigned_names

        # Check unmet minimums
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})
        for skid, qty in day_needs.items():
            minimum = skill_minimums.get(skid, 0)
            if minimum == 0:
                continue
            sname   = skill_name[skid]
            count   = len(result[date].get(sname, []))
            if count < minimum:
                unmet[date][sname] = minimum - count

    result["unmet"] = unmet

    # Update rotation history with assignments from this solve
    _update_rotation_history(conn, result, skills, staff, block_id)

    return result, None


def _update_rotation_history(conn, result, skills, staff, block_id):
    """
    After a successful solve, update rotation_history with the most recent
    date each staff member was assigned a rotation skill.
    """
    skill_id_by_name = {v["name"]: k for k, v in skills.items()}
    staff_id_by_name = {v["name"]: k for k, v in staff.items()}

    updates = {}  # (staff_id, skill_id) -> latest date

    for date, day_result in result.items():
        if date == "unmet":
            continue
        for skill_name_str, names in day_result.items():
            if skill_name_str not in ROTATION_SKILLS:
                continue
            skid = skill_id_by_name.get(skill_name_str)
            if not skid:
                continue
            for name in names:
                sid = staff_id_by_name.get(name)
                if not sid:
                    continue
                key = (sid, skid)
                if key not in updates or date > updates[key]:
                    updates[key] = date

    with conn:
        for (sid, skid), last_date in updates.items():
            conn.execute("""
                INSERT INTO rotation_history (staff_id, skill_id, last_date)
                VALUES (?, ?, ?)
                ON CONFLICT(staff_id, skill_id) DO UPDATE SET last_date = excluded.last_date
            """, (sid, skid, last_date))
        conn.commit()


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    # Use block id 1 for testing
    result, error = optimize(conn, block_id=1)
    conn.close()

    if error:
        print("Error:", error)
    else:
        unmet = result.pop("unmet")
        for date in sorted(result.keys()):
            day = result[date]
            if not day:
                continue
            print(f"\n{date} ({dt_date.fromisoformat(date).strftime('%A')})")
            for skill, names in day.items():
                print(f"  {skill}: {', '.join(names)}")
        print("\n--- Unmet ---")
        any_unmet = False
        for date, day_unmet in unmet.items():
            for skill, count in day_unmet.items():
                print(f"  {date} {skill}: {count} short")
                any_unmet = True
        if not any_unmet:
            print("  None")