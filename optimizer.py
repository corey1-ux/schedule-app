"""
optimizer.py
------------
OR-Tools CP-SAT optimizer for IR Schedule.

Hard constraints:
  - Unavailable staff cannot be assigned
  - Staff must have the skill
  - One skill per staff per day
  - TL assigned → cannot fill any other skill that day
  - FTE: exact shifts per pay period (floor AND ceiling)
  - FTE: weekly ceiling (1.0→4/wk, 0.75→3/wk, 0.6→3/wk max)
  - Rotation skills (IRC, ECU): at most once per week per staff
  - Call: excluded from optimizer entirely

Soft constraints (minimize):
  TIER 1: understaffing — penalty weighted by day priority × skill priority
          Lower priority number = more important = higher penalty
          Formula: (MAX_PRIO - day_prio) × (MAX_PRIO - skill_prio) × W_STAFFING
  TIER 2 (weight 10): moves away from staff requests
  TIER 3 (weight 1):  IRC/ECU rotation recency penalty
"""

import sqlite3
from datetime import date as dt_date, timedelta
from ortools.sat.python import cp_model

DATABASE        = "ir_schedule.db"
ROTATION_SKILLS = {"IRC", "ECU"}
WEEKEND_SKILL   = "Call"
TL_SKILL        = "TL"

W_STAFFING = 1000
W_MOVE     = 10
W_ROTATION = 1
MAX_PRIO   = 6   # priorities run 1–5, so max+1 = 6 gives meaningful weights


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(conn, block_id):
    block = conn.execute(
        "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if not block:
        raise ValueError(f"Block {block_id} not found")

    staff_rows = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
    staff = {}
    for s in staff_rows:
        skill_ids = set(
            r["skill_id"] for r in conn.execute(
                "SELECT skill_id FROM staff_skills WHERE staff_id = ?", (s["id"],)
            ).fetchall()
        )
        staff[s["id"]] = {
            "id": s["id"], "name": s["name"],
            "fte": s["fte"], "skill_ids": skill_ids,
        }

    skill_rows = conn.execute("SELECT * FROM skills ORDER BY priority, name").fetchall()
    skills = {s["id"]: dict(s) for s in skill_rows}

    need_rows = conn.execute("""
        SELECT day_of_week, skill_id, quantity
        FROM template_needs WHERE template_id = 1
    """).fetchall()
    template_needs = {}
    for r in need_rows:
        template_needs.setdefault(r["day_of_week"], {})[r["skill_id"]] = r["quantity"]

    min_rows = conn.execute(
        "SELECT skill_id, minimum_count FROM skill_minimums"
    ).fetchall()
    skill_minimums = {r["skill_id"]: r["minimum_count"] for r in min_rows}

    day_rows = conn.execute("SELECT day_of_week, priority FROM day_priority").fetchall()
    day_priority = {r["day_of_week"]: r["priority"] for r in day_rows}

    # All current assignments on the grid (requests)
    req_rows = conn.execute(
        "SELECT staff_id, date, skill_id FROM staff_requests WHERE block_id = ?",
        (block_id,)
    ).fetchall()
    requests = {(r["staff_id"], r["date"], r["skill_id"]) for r in req_rows}

    unavail_rows = conn.execute(
        "SELECT staff_id, date FROM staff_unavailability WHERE block_id = ?",
        (block_id,)
    ).fetchall()
    unavailability = {}
    for u in unavail_rows:
        unavailability.setdefault(u["staff_id"], set()).add(u["date"])

    closed = set(
        r["date"] for r in conn.execute("SELECT date FROM closed_dates").fetchall()
    )

    rot_rows = conn.execute(
        "SELECT staff_id, skill_id, last_date FROM rotation_history"
    ).fetchall()
    rotation_history = {
        (r["staff_id"], r["skill_id"]): r["last_date"] for r in rot_rows
    }

    return (block, staff, skills, template_needs, skill_minimums,
            day_priority, requests, unavailability, closed, rotation_history)


def _build_dates(block):
    start = dt_date.fromisoformat(block["start_date"])
    end   = dt_date.fromisoformat(block["end_date"])
    all_dates, weekday_dates = [], []
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


def _weekly_max(fte):
    if fte >= 1.0:  return 4
    if fte >= 0.75: return 3
    return 3


def _rotation_penalty(staff_id, skill_id, rotation_history, weekday_dates):
    key = (staff_id, skill_id)
    if key not in rotation_history:
        return 0
    last     = rotation_history[key]
    days_ago = (dt_date.fromisoformat(weekday_dates[-1]) -
                dt_date.fromisoformat(last)).days
    return max(0, 100 - days_ago)


def _staffing_weight(day_name, skill_id, day_priority, skill_prio):
    """
    Penalty weight for leaving a slot unfilled.
    Lower priority number = more important = higher weight.
    Wednesday/TL (1,1) → (6-1)×(6-1)×1000 = 25,000
    Thursday/IR RN (5,4) → (6-5)×(6-4)×1000 = 2,000
    """
    dp = day_priority.get(day_name, MAX_PRIO)
    sp = skill_prio.get(skill_id, MAX_PRIO)
    return (MAX_PRIO - dp) * (MAX_PRIO - sp) * W_STAFFING


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def optimize(conn, block_id, time_limit_seconds=60):
    (block, staff, skills, template_needs, skill_minimums,
     day_priority, requests, unavailability, closed,
     rotation_history) = _load(conn, block_id)

    all_dates, weekday_dates = _build_dates(block)
    pay_periods = _pay_periods(block)

    staff_ids = list(staff.keys())
    skill_ids = list(skills.keys())

    skill_name = {sid: skills[sid]["name"] for sid in skill_ids}
    skill_prio = {sid: skills[sid]["priority"] for sid in skill_ids}

    tl_skill_id        = next((s for s in skill_ids if skill_name[s] == TL_SKILL), None)
    rotation_skill_ids = [s for s in skill_ids if skill_name[s] in ROTATION_SKILLS]

    # Skills the optimizer assigns (no Call)
    optimizer_skill_ids = [s for s in skill_ids if skill_name[s] != WEEKEND_SKILL]

    model = cp_model.CpModel()

    # ── Decision variables ───────────────────────────────────────────────────
    x = {}
    for sid in staff_ids:
        x[sid] = {}
        for date in all_dates:
            x[sid][date] = {}
            is_weekend = dt_date.fromisoformat(date).weekday() >= 5
            for skid in optimizer_skill_ids:
                if is_weekend:
                    x[sid][date][skid] = model.NewConstant(0)
                elif date in closed:
                    x[sid][date][skid] = model.NewConstant(0)
                elif date in unavailability.get(sid, set()):
                    x[sid][date][skid] = model.NewConstant(0)
                elif skid not in staff[sid]["skill_ids"]:
                    x[sid][date][skid] = model.NewConstant(0)
                else:
                    x[sid][date][skid] = model.NewBoolVar(f"x_{sid}_{date}_{skid}")

    # ── Hard constraints ─────────────────────────────────────────────────────

    # 1. One skill per staff per day
    for sid in staff_ids:
        for date in all_dates:
            model.AddAtMostOne(
                x[sid][date][skid] for skid in optimizer_skill_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            )

    # 2. TL exclusivity
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
                    if isinstance(other_var, cp_model.IntVar):
                        model.Add(other_var == 0).OnlyEnforceIf(tl_var)

    # 3. FTE — exact floor and ceiling per pay period
    for sid in staff_ids:
        # Skip staff with no optimizer skills — they can't be scheduled
        if not any(skid in staff[sid]["skill_ids"] for skid in optimizer_skill_ids):
            continue

        target        = _fte_target(staff[sid]["fte"])
        unavail_dates = unavailability.get(sid, set())

        for p_start, p_end in pay_periods:
            period_weekday_dates = [
                d for d in weekday_dates
                if p_start.isoformat() <= d <= p_end.isoformat()
            ]
            if not period_weekday_dates:
                continue

            # Scale for partial periods at block edges
            full_weekdays = 0
            d = p_start
            while d <= p_end:
                if d.weekday() < 5:
                    full_weekdays += 1
                d += timedelta(days=1)

            actual_weekdays = len(period_weekday_dates)
            if actual_weekdays < full_weekdays:
                scaled_target = round(target * actual_weekdays / full_weekdays)
            else:
                scaled_target = target

            unavail_count = sum(1 for d in period_weekday_dates if d in unavail_dates)
            required      = max(0, scaled_target - unavail_count)

            period_vars = []
            for date in period_weekday_dates:
                if date in unavail_dates:
                    continue
                for skid in optimizer_skill_ids:
                    v = x[sid][date][skid]
                    if isinstance(v, cp_model.IntVar):
                        period_vars.append(v)

            if period_vars:
                model.Add(sum(period_vars) <= scaled_target)

    # 4. Weekly FTE ceiling + rotation once-per-week (combined loop)
    blk_start = dt_date.fromisoformat(block["start_date"])
    blk_end   = dt_date.fromisoformat(block["end_date"])
    wk = blk_start - timedelta(days=blk_start.weekday())
    while wk <= blk_end:
        wk_end = wk + timedelta(days=6)

        for sid in staff_ids:
            # Skip staff with no optimizer skills
            if not any(skid in staff[sid]["skill_ids"] for skid in optimizer_skill_ids):
                continue
            fte = staff[sid]["fte"]
            unavail_dates = unavailability.get(sid, set())
            week_weekday_dates = [
                d for d in weekday_dates
                if wk.isoformat() <= d <= wk_end.isoformat()
            ]
            if not week_weekday_dates:
                continue

            week_vars = [
                x[sid][date][skid]
                for date in week_weekday_dates
                if date not in unavail_dates
                for skid in optimizer_skill_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if week_vars:
                model.Add(sum(week_vars) <= _weekly_max(fte))

        # Rotation: at most once per week per staff
        # Exception: staff whose only skill IS the rotation skill
        # (e.g. Julia/Kathy who can only do ECU) — they are not rotating,
        # ECU is just their job. No weekly limit for them.
        for skid in rotation_skill_ids:
            for sid in staff_ids:
                if skid not in staff[sid]["skill_ids"]:
                    continue
                opt_skills = [s for s in staff[sid]["skill_ids"]
                              if s in optimizer_skill_ids]
                if len(opt_skills) == 1:
                    continue  # single-skill staff — no rotation limit
                rot_vars = [
                    x[sid][date][skid]
                    for date in weekday_dates
                    if wk.isoformat() <= date <= wk_end.isoformat()
                    and isinstance(x[sid][date][skid], cp_model.IntVar)
                ]
                if rot_vars:
                    model.AddAtMostOne(rot_vars)

        wk = wk_end + timedelta(days=1)

    # 5. Hard minimum staffing per day per skill
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})
        for skid, qty in day_needs.items():
            if skid not in optimizer_skill_ids:
                continue
            minimum = skill_minimums.get(skid, 0)
            if minimum == 0:
                continue
            assigned = [
                x[sid][date][skid] for sid in staff_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if assigned:
                model.Add(sum(assigned) >= minimum)

    # 5b. Hard FTE floor for single-skill staff
    # If a staff member only has one optimizer skill, they must hit their
    # FTE target — otherwise they can never reach it.
    for sid in staff_ids:
        skill_options = [s for s in staff[sid]["skill_ids"] if s in optimizer_skill_ids]
        if len(skill_options) == 0:
            continue  # no skills — skip entirely
        if len(skill_options) > 1:
            continue  # multi-skilled — soft FTE is fine

        target        = _fte_target(staff[sid]["fte"])
        unavail_dates = unavailability.get(sid, set())

        for p_start, p_end in pay_periods:
            period_weekday_dates = [
                d for d in weekday_dates
                if p_start.isoformat() <= d <= p_end.isoformat()
            ]
            if not period_weekday_dates:
                continue

            full_weekdays = 0
            d = p_start
            while d <= p_end:
                if d.weekday() < 5:
                    full_weekdays += 1
                d += timedelta(days=1)

            actual_weekdays = len(period_weekday_dates)
            if actual_weekdays < full_weekdays:
                scaled_target = round(target * actual_weekdays / full_weekdays)
            else:
                scaled_target = target

            unavail_count = sum(1 for d in period_weekday_dates if d in unavail_dates)
            required      = max(0, scaled_target - unavail_count)

            period_vars = [
                x[sid][date][skid]
                for date in period_weekday_dates
                if date not in unavail_dates
                for skid in optimizer_skill_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if period_vars and required > 0:
                model.Add(sum(period_vars) >= required)

    # 5c. Hard daily maximums for specific skills
    DAILY_MAX = {
        skill_id: qty
        for skill_id, qty in [
            (next((s for s in skill_ids if skill_name[s] == "TL"), None), 1),
            (next((s for s in skill_ids if skill_name[s] == "IRC"), None), 1),
            (next((s for s in skill_ids if skill_name[s] == "ECU"), None), 2),
        ]
        if skill_id is not None
    }

    for date in weekday_dates:
        if date in closed:
            continue
        for skid, max_count in DAILY_MAX.items():
            assigned = [
                x[sid][date][skid] for sid in staff_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if assigned:
                model.Add(sum(assigned) <= max_count)

    # ── Soft constraints (objective) ─────────────────────────────────────────
    penalties = []

    # TIER 1: Understaffing — weighted by day × skill priority
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})

        for skid, qty in day_needs.items():
            if skid not in optimizer_skill_ids:
                continue
            weight = _staffing_weight(day_name, skid, day_priority, skill_prio)
            if weight == 0:
                continue

            assigned = [
                x[sid][date][skid] for sid in staff_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if not assigned:
                continue

            # Penalize each unfilled slot up to the target quantity
            shortage = model.NewIntVar(0, qty, f"short_{date}_{skid}")
            model.Add(shortage >= qty - sum(assigned))
            model.Add(shortage >= 0)
            penalties.append(weight * shortage)

    # TIER 1b: Under-FTE penalty — encourage hitting the target
    # Weight is high enough to prefer full FTE but lower than staffing needs
    W_FTE_UNDER = 500
    for sid in staff_ids:
        target        = _fte_target(staff[sid]["fte"])
        unavail_dates = unavailability.get(sid, set())

        for p_start, p_end in pay_periods:
            period_weekday_dates = [
                d for d in weekday_dates
                if p_start.isoformat() <= d <= p_end.isoformat()
            ]
            if not period_weekday_dates:
                continue

            full_weekdays = 0
            d = p_start
            while d <= p_end:
                if d.weekday() < 5:
                    full_weekdays += 1
                d += timedelta(days=1)

            actual_weekdays = len(period_weekday_dates)
            if actual_weekdays < full_weekdays:
                scaled_target = round(target * actual_weekdays / full_weekdays)
            else:
                scaled_target = target

            unavail_count = sum(1 for d in period_weekday_dates if d in unavail_dates)
            required      = max(0, scaled_target - unavail_count)

            period_vars = [
                x[sid][date][skid]
                for date in period_weekday_dates
                if date not in unavail_dates
                for skid in optimizer_skill_ids
                if isinstance(x[sid][date][skid], cp_model.IntVar)
            ]
            if period_vars and required > 0:
                under = model.NewIntVar(0, required, f"fte_under_{sid}_{p_start}")
                model.Add(under >= required - sum(period_vars))
                model.Add(under >= 0)
                penalties.append(W_FTE_UNDER * under)

    # TIER 1c: Rotation fairness across pay periods
    # For rotation skills (ECU, IRC), spread assignments evenly among eligible
    # multi-skilled staff. Single-skill staff (Julia, Kathy) are excluded
    # since ECU is their only job — they should always get it.
    for skid in rotation_skill_ids:
        eligible_multi = [
            sid for sid in staff_ids
            if skid in staff[sid]["skill_ids"]
            and len([s for s in staff[sid]["skill_ids"] if s in optimizer_skill_ids]) > 1
        ]
        if len(eligible_multi) < 2:
            continue

        # For each pay period, penalize imbalance among multi-skilled staff
        for p_start, p_end in pay_periods:
            period_vars_by_staff = {}
            for sid in eligible_multi:
                pvars = [
                    x[sid][date][skid]
                    for date in weekday_dates
                    if p_start.isoformat() <= date <= p_end.isoformat()
                    and isinstance(x[sid][date][skid], cp_model.IntVar)
                ]
                if pvars:
                    period_vars_by_staff[sid] = pvars

            if len(period_vars_by_staff) < 2:
                continue

            # Create sum variable for each staff member
            sums = {}
            max_possible = len(pay_periods) * 3  # upper bound
            for sid, pvars in period_vars_by_staff.items():
                s = model.NewIntVar(0, max_possible, f"rot_sum_{skid}_{sid}_{p_start}")
                model.Add(s == sum(pvars))
                sums[sid] = s

            # Penalize max - min spread
            sum_list = list(sums.values())
            max_sum  = model.NewIntVar(0, max_possible, f"rot_max_{skid}_{p_start}")
            min_sum  = model.NewIntVar(0, max_possible, f"rot_min_{skid}_{p_start}")
            model.AddMaxEquality(max_sum, sum_list)
            model.AddMinEquality(min_sum, sum_list)
            spread = model.NewIntVar(0, max_possible, f"rot_spread_{skid}_{p_start}")
            model.Add(spread == max_sum - min_sum)
            penalties.append(W_STAFFING * spread)

    # TIER 2: Moves away from staff requests
    for (sid, date, skid) in requests:
        if sid not in staff or skid not in skills:
            continue
        if skid not in optimizer_skill_ids:
            continue
        v = x.get(sid, {}).get(date, {}).get(skid)
        if v is None or not isinstance(v, cp_model.IntVar):
            continue
        not_honored = model.NewBoolVar(f"move_{sid}_{date}_{skid}")
        model.Add(not_honored == 1 - v)
        penalties.append(W_MOVE * not_honored)

    # TIER 3: Rotation recency penalty
    for skid in rotation_skill_ids:
        for sid in staff_ids:
            if skid not in staff[sid]["skill_ids"]:
                continue
            pen = _rotation_penalty(sid, skid, rotation_history, weekday_dates)
            if pen == 0:
                continue
            for date in weekday_dates:
                v = x[sid][date].get(skid)
                if isinstance(v, cp_model.IntVar):
                    penalties.append(W_ROTATION * pen * v)

    model.Minimize(sum(penalties) if penalties else model.NewConstant(0))

    # ── Solve ────────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers  = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Diagnostics
        diag = []
        for sid in staff_ids:
            target = _fte_target(staff[sid]["fte"])
            unavail_dates = unavailability.get(sid, set())
            valid_slots = sum(
                1 for d in weekday_dates
                if d not in unavail_dates
                and any(
                    isinstance(x[sid][d][skid], cp_model.IntVar)
                    for skid in optimizer_skill_ids
                )
            )
            total_needed = target * len(pay_periods)
            if valid_slots < total_needed:
                diag.append(
                    f"  {staff[sid]['name']} (FTE {staff[sid]['fte']}): "
                    f"needs {total_needed} shifts but only {valid_slots} valid slots"
                )
        msg = "No feasible solution found."
        if diag:
            msg += " Staff with insufficient slots:\n" + "\n".join(diag)
        else:
            msg += " The FTE requirements and staffing minimums conflict. "
            msg += "Check that total staff shifts can cover all required slots."
        return None, msg

    # ── Extract result ────────────────────────────────────────────────────────
    result = {}
    unmet  = {}

    for date in all_dates:
        result[date] = {}
        unmet[date]  = {}
        day_name = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})

        for skid in optimizer_skill_ids:
            sname = skill_name[skid]
            names = [
                staff[sid]["name"]
                for sid in staff_ids
                if (solver.Value(x[sid][date][skid])
                    if isinstance(x[sid][date][skid], cp_model.IntVar)
                    else int(x[sid][date][skid])) == 1
            ]
            if names:
                result[date][sname] = names

        for skid, qty in day_needs.items():
            if skid not in optimizer_skill_ids:
                continue
            sname = skill_name[skid]
            count = len(result[date].get(sname, []))
            if count < qty:
                unmet[date][sname] = qty - count

    result["unmet"] = unmet

    _update_rotation_history(conn, result, skills, staff)
    return result, None


def _update_rotation_history(conn, result, skills, staff):
    skill_id_by_name = {v["name"]: k for k, v in skills.items()}
    staff_id_by_name = {v["name"]: k for k, v in staff.items()}
    updates = {}

    for date, day_result in result.items():
        if date == "unmet":
            continue
        for sname, names in day_result.items():
            if sname not in ROTATION_SKILLS:
                continue
            skid = skill_id_by_name.get(sname)
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
                ON CONFLICT(staff_id, skill_id) DO UPDATE SET
                    last_date = excluded.last_date
            """, (sid, skid, last_date))
        conn.commit()


if __name__ == "__main__":
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
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