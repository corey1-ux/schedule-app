"""
optimizer.py
------------
OR-Tools CP-SAT optimizer for IR Schedule.

Hard constraints:
  - Unavailable staff cannot be assigned
  - Staff must have the skill
  - One skill per staff per day
  - TL assigned → cannot fill any other skill that day
  - FTE: ceiling per pay period (scaled for partial periods)
  - FTE: floor per pay period for single-skill staff
  - FTE: weekly ceiling (1.0→4/wk, 0.75→3/wk, 0.6→3/wk max)
  - Rotation skills (IRC, ECU): at most once per week per staff
  - Call: excluded from optimizer entirely

Soft constraints (minimize):
  TIER 1:  understaffing — penalty weighted by day priority × skill priority
           Lower priority number = more important = higher penalty
           Formula: (MAX_PRIO - day_prio) × (MAX_PRIO - skill_prio) × W_STAFFING
  TIER 1b: under-FTE — encourage hitting pay-period targets
  TIER 1c: rotation fairness — spread IRC/ECU evenly among multi-skilled staff
  TIER 2  (weight 10): moves away from staff requests
  TIER 3  (weight  1): IRC/ECU rotation recency penalty
"""

import sqlite3
from datetime import date as dt_date, timedelta
from ortools.sat.python import cp_model

DATABASE        = "ir_schedule.db"
ROTATION_SKILLS = {"IRC", "ECU"}
WEEKEND_SKILL   = "Call"
TL_SKILL        = "TL"

W_STAFFING  = 1000
W_FTE_UNDER = 500
W_MOVE      = 10
W_ROTATION  = 1
MAX_PRIO    = 6   # priorities run 1–5; (MAX_PRIO - prio) gives the weight multiplier


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(conn, block_id):
    block = conn.execute(
        "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if not block:
        raise ValueError(f"Block {block_id} not found")

    staff_rows = conn.execute(
        "SELECT * FROM staff WHERE is_casual = 0 OR is_casual IS NULL ORDER BY name"
    ).fetchall()
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

    tier_rows = conn.execute(
        "SELECT fte, shifts_per_week, shifts_per_pp FROM fte_tiers ORDER BY fte"
    ).fetchall()
    fte_tiers = [(r["fte"], r["shifts_per_week"], r["shifts_per_pp"]) for r in tier_rows]

    return (block, staff, skills, template_needs, skill_minimums,
            day_priority, requests, unavailability, closed, rotation_history,
            fte_tiers)


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


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _lookup_fte(fte_tiers, fte):
    """
    Return (shifts_per_week, shifts_per_pp) for the given FTE value.
    Tries exact match first, then nearest tier at or below, then lowest tier.
    """
    sorted_tiers = sorted(fte_tiers, key=lambda t: t[0], reverse=True)
    for tier_fte, weekly, pp in sorted_tiers:
        if abs(tier_fte - fte) < 0.001:
            return weekly, pp
    for tier_fte, weekly, pp in sorted_tiers:
        if tier_fte <= fte:
            return weekly, pp
    if sorted_tiers:
        return sorted_tiers[-1][1], sorted_tiers[-1][2]
    return 3, 5  # ultimate fallback


def _rotation_penalty(staff_id, skill_id, rotation_history, weekday_dates):
    key = (staff_id, skill_id)
    if key not in rotation_history:
        return 0
    days_ago = (dt_date.fromisoformat(weekday_dates[-1]) -
                dt_date.fromisoformat(rotation_history[key])).days
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


def _period_targets(target, p_start, p_end, weekday_dates, unavail_dates):
    """
    Compute FTE shift counts for one pay period.

    Returns (avail_dates, scaled_target, required) where:
      avail_dates   - weekday dates in period when staff is available
      scaled_target - prorated shift count (handles partial periods at block edges)
      required      - hard floor = max(0, scaled_target - unavail_count)
    """
    all_period_dates = [
        d for d in weekday_dates
        if p_start.isoformat() <= d <= p_end.isoformat()
    ]
    if not all_period_dates:
        return [], 0, 0

    # A pay period is always 14 calendar days
    full_weekdays = sum(
        1 for i in range(14)
        if (p_start + timedelta(days=i)).weekday() < 5
    )
    actual = len(all_period_dates)
    scaled_target = round(target * actual / full_weekdays) if actual < full_weekdays else target

    unavail_count = sum(1 for d in all_period_dates if d in unavail_dates)
    required      = max(0, scaled_target - unavail_count)
    avail_dates   = [d for d in all_period_dates if d not in unavail_dates]
    return avail_dates, scaled_target, required


def _period_vars(x, staff_id, avail_dates, optimizer_skill_ids):
    """All decision variables for a staff member over their available dates in a period."""
    return [
        x[(staff_id, d, skid)]
        for d in avail_dates
        for skid in optimizer_skill_ids
        if (staff_id, d, skid) in x
    ]


def _has_optimizer_skills(staff_member, optimizer_skill_ids):
    return any(skid in staff_member["skill_ids"] for skid in optimizer_skill_ids)


def _is_single_skill(staff_member, optimizer_skill_ids):
    return sum(1 for s in staff_member["skill_ids"] if s in optimizer_skill_ids) == 1


# ---------------------------------------------------------------------------
# Variable builder
# ---------------------------------------------------------------------------

def _build_variables(model, staff, staff_ids, optimizer_skill_ids,
                     weekday_dates, closed, unavailability):
    """
    Return a sparse dict x: (staff_id, date, skill_id) -> BoolVar.
    Only valid triples are included — invalid combinations (unavailable,
    wrong skill, closed day) simply have no entry.
    """
    x = {}
    for staff_id in staff_ids:
        unavail  = unavailability.get(staff_id, set())
        skill_set = staff[staff_id]["skill_ids"]
        for date in weekday_dates:
            if date in closed or date in unavail:
                continue
            for skid in optimizer_skill_ids:
                if skid in skill_set:
                    x[(staff_id, date, skid)] = model.NewBoolVar(
                        f"x_{staff_id}_{date}_{skid}"
                    )
    return x


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------

def _add_one_skill_per_day(model, x, staff_ids, weekday_dates, optimizer_skill_ids):
    """Each staff member works at most one skill per day."""
    for staff_id in staff_ids:
        for date in weekday_dates:
            day_vars = [
                x[(staff_id, date, skid)]
                for skid in optimizer_skill_ids
                if (staff_id, date, skid) in x
            ]
            if len(day_vars) > 1:
                model.AddAtMostOne(day_vars)


def _add_tl_exclusivity(model, x, staff_ids, weekday_dates, optimizer_skill_ids,
                        tl_skill_id, staff):
    """If assigned as TL, staff cannot fill any other skill that day."""
    if not tl_skill_id:
        return
    for staff_id in staff_ids:
        if tl_skill_id not in staff[staff_id]["skill_ids"]:
            continue
        for date in weekday_dates:
            tl_key = (staff_id, date, tl_skill_id)
            if tl_key not in x:
                continue
            tl_var = x[tl_key]
            for skid in optimizer_skill_ids:
                if skid == tl_skill_id:
                    continue
                other_key = (staff_id, date, skid)
                if other_key in x:
                    model.Add(x[other_key] == 0).OnlyEnforceIf(tl_var)


def _add_fte_ceiling(model, x, staff_ids, weekday_dates, pay_periods,
                     optimizer_skill_ids, staff, fte_tiers, unavailability):
    """Total shifts per pay period must not exceed the (scaled) FTE target."""
    for staff_id in staff_ids:
        if not _has_optimizer_skills(staff[staff_id], optimizer_skill_ids):
            continue
        target = _lookup_fte(fte_tiers, staff[staff_id]["fte"])[1]
        unavail = unavailability.get(staff_id, set())
        for p_start, p_end in pay_periods:
            avail_dates, scaled_target, _ = _period_targets(
                target, p_start, p_end, weekday_dates, unavail
            )
            pvars = _period_vars(x, staff_id, avail_dates, optimizer_skill_ids)
            if pvars:
                model.Add(sum(pvars) <= scaled_target)


def _add_fte_floor_single_skill(model, x, staff_ids, weekday_dates, pay_periods,
                                optimizer_skill_ids, staff, fte_tiers, unavailability):
    """
    For single-skill staff, enforce the hard FTE floor per pay period.
    Multi-skilled staff get a soft floor via the objective instead.
    """
    for staff_id in staff_ids:
        if not _is_single_skill(staff[staff_id], optimizer_skill_ids):
            continue
        target = _lookup_fte(fte_tiers, staff[staff_id]["fte"])[1]
        unavail = unavailability.get(staff_id, set())
        for p_start, p_end in pay_periods:
            avail_dates, _, required = _period_targets(
                target, p_start, p_end, weekday_dates, unavail
            )
            pvars = _period_vars(x, staff_id, avail_dates, optimizer_skill_ids)
            if pvars and required > 0:
                model.Add(sum(pvars) >= required)


def _add_weekly_fte_ceiling(model, x, staff_ids, weekday_dates, optimizer_skill_ids,
                            staff, fte_tiers, unavailability, blk_start, blk_end):
    """Weekly shift count must not exceed the FTE tier's weekly cap."""
    wk = blk_start - timedelta(days=blk_start.weekday())
    while wk <= blk_end:
        wk_end = wk + timedelta(days=6)
        for staff_id in staff_ids:
            if not _has_optimizer_skills(staff[staff_id], optimizer_skill_ids):
                continue
            unavail = unavailability.get(staff_id, set())
            week_vars = [
                x[(staff_id, d, skid)]
                for d in weekday_dates
                if wk.isoformat() <= d <= wk_end.isoformat() and d not in unavail
                for skid in optimizer_skill_ids
                if (staff_id, d, skid) in x
            ]
            if week_vars:
                weekly_max = _lookup_fte(fte_tiers, staff[staff_id]["fte"])[0]
                model.Add(sum(week_vars) <= weekly_max)
        wk = wk_end + timedelta(days=1)


def _add_rotation_once_per_week(model, x, staff_ids, weekday_dates,
                                rotation_skill_ids, optimizer_skill_ids,
                                staff, blk_start, blk_end):
    """
    Multi-skilled staff may hold a rotation skill (IRC/ECU) at most once per week.
    Single-skill staff are exempt — the rotation skill is simply their job.
    """
    wk = blk_start - timedelta(days=blk_start.weekday())
    while wk <= blk_end:
        wk_end = wk + timedelta(days=6)
        for skid in rotation_skill_ids:
            for staff_id in staff_ids:
                if skid not in staff[staff_id]["skill_ids"]:
                    continue
                if _is_single_skill(staff[staff_id], optimizer_skill_ids):
                    continue  # ECU/IRC is just their job — no weekly limit
                rot_vars = [
                    x[(staff_id, d, skid)]
                    for d in weekday_dates
                    if wk.isoformat() <= d <= wk_end.isoformat()
                    and (staff_id, d, skid) in x
                ]
                if rot_vars:
                    model.AddAtMostOne(rot_vars)
        wk = wk_end + timedelta(days=1)


def _add_staffing_minimums(model, x, staff_ids, weekday_dates, optimizer_skill_ids,
                           template_needs, skill_minimums, closed):
    """Hard minimum staffing per day per skill."""
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        for skid in template_needs.get(day_name, {}):
            if skid not in optimizer_skill_ids:
                continue
            minimum = skill_minimums.get(skid, 0)
            if minimum == 0:
                continue
            assigned = [x[(sid, date, skid)] for sid in staff_ids if (sid, date, skid) in x]
            if assigned:
                model.Add(sum(assigned) >= minimum)


def _add_daily_maximums(model, x, staff_ids, weekday_dates, skill_ids,
                        skill_name, closed):
    """Hard daily caps for specific skills: TL=1, IRC=1, ECU=2."""
    skill_by_name = {skill_name[sid]: sid for sid in skill_ids}
    daily_max = {
        skill_by_name[name]: cap
        for name, cap in [("TL", 1), ("IRC", 1), ("ECU", 2)]
        if name in skill_by_name
    }
    for date in weekday_dates:
        if date in closed:
            continue
        for skid, cap in daily_max.items():
            assigned = [x[(sid, date, skid)] for sid in staff_ids if (sid, date, skid) in x]
            if assigned:
                model.Add(sum(assigned) <= cap)


def _add_hard_constraints(model, x, staff_ids, weekday_dates, pay_periods,
                          optimizer_skill_ids, rotation_skill_ids, tl_skill_id,
                          skill_ids, skill_name, staff, fte_tiers, unavailability,
                          template_needs, skill_minimums, closed, blk_start, blk_end):
    _add_one_skill_per_day(
        model, x, staff_ids, weekday_dates, optimizer_skill_ids)
    _add_tl_exclusivity(
        model, x, staff_ids, weekday_dates, optimizer_skill_ids, tl_skill_id, staff)
    _add_fte_ceiling(
        model, x, staff_ids, weekday_dates, pay_periods,
        optimizer_skill_ids, staff, fte_tiers, unavailability)
    _add_fte_floor_single_skill(
        model, x, staff_ids, weekday_dates, pay_periods,
        optimizer_skill_ids, staff, fte_tiers, unavailability)
    _add_weekly_fte_ceiling(
        model, x, staff_ids, weekday_dates, optimizer_skill_ids,
        staff, fte_tiers, unavailability, blk_start, blk_end)
    _add_rotation_once_per_week(
        model, x, staff_ids, weekday_dates, rotation_skill_ids,
        optimizer_skill_ids, staff, blk_start, blk_end)
    _add_staffing_minimums(
        model, x, staff_ids, weekday_dates, optimizer_skill_ids,
        template_needs, skill_minimums, closed)
    _add_daily_maximums(
        model, x, staff_ids, weekday_dates, skill_ids, skill_name, closed)


# ---------------------------------------------------------------------------
# Objective (soft constraints by tier)
# ---------------------------------------------------------------------------

def _tier1_understaffing(model, x, staff_ids, weekday_dates, optimizer_skill_ids,
                         template_needs, day_priority, skill_prio, closed):
    """Penalize each unfilled slot, weighted by day and skill priority."""
    penalties = []
    for date in weekday_dates:
        if date in closed:
            continue
        day_name = dt_date.fromisoformat(date).strftime("%A")
        for skid, qty in template_needs.get(day_name, {}).items():
            if skid not in optimizer_skill_ids:
                continue
            weight = _staffing_weight(day_name, skid, day_priority, skill_prio)
            if weight == 0:
                continue
            assigned = [x[(sid, date, skid)] for sid in staff_ids if (sid, date, skid) in x]
            if not assigned:
                continue
            shortage = model.NewIntVar(0, qty, f"short_{date}_{skid}")
            model.Add(shortage >= qty - sum(assigned))
            penalties.append(weight * shortage)
    return penalties


def _tier1b_fte_under(model, x, staff_ids, weekday_dates, pay_periods,
                      optimizer_skill_ids, staff, fte_tiers, unavailability):
    """Penalize falling short of the FTE pay-period target."""
    penalties = []
    for staff_id in staff_ids:
        target  = _lookup_fte(fte_tiers, staff[staff_id]["fte"])[1]
        unavail = unavailability.get(staff_id, set())
        for p_start, p_end in pay_periods:
            avail_dates, _, required = _period_targets(
                target, p_start, p_end, weekday_dates, unavail
            )
            pvars = _period_vars(x, staff_id, avail_dates, optimizer_skill_ids)
            if pvars and required > 0:
                under = model.NewIntVar(0, required, f"fte_under_{staff_id}_{p_start}")
                model.Add(under >= required - sum(pvars))
                penalties.append(W_FTE_UNDER * under)
    return penalties


def _tier1c_rotation_fairness(model, x, staff_ids, weekday_dates, pay_periods,
                              rotation_skill_ids, optimizer_skill_ids, staff):
    """
    Penalize uneven spread of rotation skills among eligible multi-skilled staff.
    Single-skill staff (whose only skill is a rotation skill) are excluded.
    """
    penalties = []
    for skid in rotation_skill_ids:
        eligible = [
            sid for sid in staff_ids
            if skid in staff[sid]["skill_ids"]
            and not _is_single_skill(staff[sid], optimizer_skill_ids)
        ]
        if len(eligible) < 2:
            continue
        max_possible = len(pay_periods) * 3  # conservative upper bound
        for p_start, p_end in pay_periods:
            sums = {}
            for sid in eligible:
                pvars = [
                    x[(sid, d, skid)]
                    for d in weekday_dates
                    if p_start.isoformat() <= d <= p_end.isoformat()
                    and (sid, d, skid) in x
                ]
                if pvars:
                    s = model.NewIntVar(0, max_possible, f"rot_sum_{skid}_{sid}_{p_start}")
                    model.Add(s == sum(pvars))
                    sums[sid] = s
            if len(sums) < 2:
                continue
            sum_list = list(sums.values())
            max_s  = model.NewIntVar(0, max_possible, f"rot_max_{skid}_{p_start}")
            min_s  = model.NewIntVar(0, max_possible, f"rot_min_{skid}_{p_start}")
            spread = model.NewIntVar(0, max_possible, f"rot_spread_{skid}_{p_start}")
            model.AddMaxEquality(max_s, sum_list)
            model.AddMinEquality(min_s, sum_list)
            model.Add(spread == max_s - min_s)
            penalties.append(W_STAFFING * spread)
    return penalties


def _tier2_request_moves(model, x, requests, staff, skills, optimizer_skill_ids):
    """Penalize assignments that differ from staff requests."""
    penalties = []
    for staff_id, date, skid in requests:
        if staff_id not in staff or skid not in skills:
            continue
        if skid not in optimizer_skill_ids:
            continue
        key = (staff_id, date, skid)
        if key not in x:
            continue
        not_honored = model.NewBoolVar(f"move_{staff_id}_{date}_{skid}")
        model.Add(not_honored == 1 - x[key])
        penalties.append(W_MOVE * not_honored)
    return penalties


def _tier3_rotation_recency(x, staff_ids, weekday_dates, rotation_skill_ids,
                            staff, rotation_history):
    """Penalize assigning a rotation skill to someone who did it recently."""
    penalties = []
    for skid in rotation_skill_ids:
        for staff_id in staff_ids:
            if skid not in staff[staff_id]["skill_ids"]:
                continue
            pen = _rotation_penalty(staff_id, skid, rotation_history, weekday_dates)
            if pen == 0:
                continue
            for date in weekday_dates:
                key = (staff_id, date, skid)
                if key in x:
                    penalties.append(W_ROTATION * pen * x[key])
    return penalties


def _build_objective(model, x, staff_ids, weekday_dates, pay_periods,
                     optimizer_skill_ids, rotation_skill_ids, staff, fte_tiers,
                     unavailability, template_needs, day_priority, skill_prio,
                     requests, skills, rotation_history, closed):
    penalties = (
        _tier1_understaffing(
            model, x, staff_ids, weekday_dates, optimizer_skill_ids,
            template_needs, day_priority, skill_prio, closed)
        + _tier1b_fte_under(
            model, x, staff_ids, weekday_dates, pay_periods,
            optimizer_skill_ids, staff, fte_tiers, unavailability)
        + _tier1c_rotation_fairness(
            model, x, staff_ids, weekday_dates, pay_periods,
            rotation_skill_ids, optimizer_skill_ids, staff)
        + _tier2_request_moves(
            model, x, requests, staff, skills, optimizer_skill_ids)
        + _tier3_rotation_recency(
            x, staff_ids, weekday_dates, rotation_skill_ids,
            staff, rotation_history)
    )
    if penalties:
        model.Minimize(sum(penalties))


# ---------------------------------------------------------------------------
# Result extraction & diagnostics
# ---------------------------------------------------------------------------

def _extract_result(solver, x, staff, staff_ids, all_dates, optimizer_skill_ids,
                    skill_name, template_needs):
    result = {}
    unmet  = {}
    for date in all_dates:
        result[date] = {}
        day_name  = dt_date.fromisoformat(date).strftime("%A")
        day_needs = template_needs.get(day_name, {})

        for skid in optimizer_skill_ids:
            assigned_names = [
                staff[sid]["name"]
                for sid in staff_ids
                if (sid, date, skid) in x and solver.Value(x[(sid, date, skid)]) == 1
            ]
            if assigned_names:
                result[date][skill_name[skid]] = assigned_names

        day_unmet = {
            skill_name[skid]: qty - len(result[date].get(skill_name[skid], []))
            for skid, qty in day_needs.items()
            if skid in optimizer_skill_ids
            and qty - len(result[date].get(skill_name[skid], [])) > 0
        }
        if day_unmet:
            unmet[date] = day_unmet

    result["unmet"] = unmet
    return result


def _diagnose_infeasible(staff, staff_ids, weekday_dates, x,
                         pay_periods, fte_tiers, optimizer_skill_ids):
    """
    Identify staff members whose available slots cannot satisfy their FTE target.
    Returns a list of diagnostic strings (empty if no obvious conflict found).
    """
    lines = []
    for staff_id in staff_ids:
        target = _lookup_fte(fte_tiers, staff[staff_id]["fte"])[1]
        valid_slots = sum(
            1 for d in weekday_dates
            if any((staff_id, d, skid) in x for skid in optimizer_skill_ids)
        )
        total_needed = target * len(pay_periods)
        if valid_slots < total_needed:
            lines.append(
                f"  {staff[staff_id]['name']} (FTE {staff[staff_id]['fte']}): "
                f"needs {total_needed} shifts but only {valid_slots} valid slots"
            )

    return lines


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def optimize(conn, block_id, time_limit_seconds=60):
    # ── Load ──────────────────────────────────────────────────────────────────
    (block, staff, skills, template_needs, skill_minimums,
     day_priority, requests, unavailability, closed,
     rotation_history, fte_tiers) = _load(conn, block_id)

    all_dates, weekday_dates = _build_dates(block)
    pay_periods = _pay_periods(block)

    staff_ids  = list(staff.keys())
    skill_ids  = list(skills.keys())
    skill_name = {sid: skills[sid]["name"] for sid in skill_ids}
    skill_prio = {sid: skills[sid]["priority"] for sid in skill_ids}

    tl_skill_id         = next((s for s in skill_ids if skill_name[s] == TL_SKILL), None)
    rotation_skill_ids  = [s for s in skill_ids if skill_name[s] in ROTATION_SKILLS]
    optimizer_skill_ids = [s for s in skill_ids if skill_name[s] != WEEKEND_SKILL]

    blk_start = dt_date.fromisoformat(block["start_date"])
    blk_end   = dt_date.fromisoformat(block["end_date"])

    # ── Build model ───────────────────────────────────────────────────────────
    model = cp_model.CpModel()
    x = _build_variables(
        model, staff, staff_ids, optimizer_skill_ids,
        weekday_dates, closed, unavailability,
    )

    # ── Hard constraints ──────────────────────────────────────────────────────
    _add_hard_constraints(
        model, x, staff_ids, weekday_dates, pay_periods,
        optimizer_skill_ids, rotation_skill_ids, tl_skill_id,
        skill_ids, skill_name, staff, fte_tiers, unavailability,
        template_needs, skill_minimums, closed, blk_start, blk_end,
    )

    # ── Objective ─────────────────────────────────────────────────────────────
    _build_objective(
        model, x, staff_ids, weekday_dates, pay_periods,
        optimizer_skill_ids, rotation_skill_ids, staff, fte_tiers,
        unavailability, template_needs, day_priority, skill_prio,
        requests, skills, rotation_history, closed,
    )

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers  = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        diag = _diagnose_infeasible(
            staff, staff_ids, weekday_dates, x,
            pay_periods, fte_tiers, optimizer_skill_ids,
        )
        msg = "No feasible solution found."
        if diag:
            msg += " Staff with insufficient slots:\n" + "\n".join(diag)
        else:
            msg += (" The FTE requirements and staffing minimums conflict. "
                    "Check that total staff shifts can cover all required slots.")
        return None, msg

    # ── Extract ───────────────────────────────────────────────────────────────
    result = _extract_result(
        solver, x, staff, staff_ids, all_dates,
        optimizer_skill_ids, skill_name, template_needs,
    )
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
