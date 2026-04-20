import sqlite3
from collections import defaultdict
from datetime import date as dt_date, timedelta

DATABASE      = "ir_schedule.db"
TL_SKILL      = "TL"
ECU_SKILL     = "ECU"
IRC_SKILL     = "IRC"
IR_RN_SKILL   = "IR RN"
IR_LATE_SKILL = "IR Late"
ECU_DAILY_CAP = 2
IRC_DAILY_CAP = 1


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_block(conn, block_id):
    block = conn.execute(
        "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if not block:
        raise ValueError(f"Block {block_id} not found")
    return block


def _load_staff(conn):
    rows = conn.execute(
        "SELECT * FROM staff WHERE is_casual = 0 OR is_casual IS NULL ORDER BY name"
    ).fetchall()
    staff = {}
    for s in rows:
        skill_ids = set(
            r["skill_id"] for r in conn.execute(
                "SELECT skill_id FROM staff_skills WHERE staff_id = ?", (s["id"],)
            ).fetchall()
        )
        staff[s["id"]] = {
            "id": s["id"], "name": s["name"],
            "fte": s["fte"], "skill_ids": skill_ids,
        }
    return staff


def _load_skills(conn):
    rows = conn.execute("SELECT * FROM skills ORDER BY priority, name").fetchall()
    return {s["id"]: dict(s) for s in rows}


def _load_template_needs(conn):
    rows = conn.execute(
        "SELECT day_of_week, skill_id, quantity FROM template_needs WHERE template_id = 1"
    ).fetchall()
    needs = {}
    for r in rows:
        needs.setdefault(r["day_of_week"], {})[r["skill_id"]] = r["quantity"]
    return needs


def _load_unavailability(conn, block_id):
    rows = conn.execute(
        "SELECT staff_id, date FROM staff_unavailability WHERE block_id = ?",
        (block_id,)
    ).fetchall()
    unavail = {}
    for u in rows:
        unavail.setdefault(u["staff_id"], set()).add(u["date"])
    return unavail


def _load_closed_dates(conn):
    rows = conn.execute("SELECT date FROM closed_dates").fetchall()
    return {r["date"] for r in rows}


def _load_fte_tiers(conn):
    rows = conn.execute(
        "SELECT fte, shifts_per_week, shifts_per_pp FROM fte_tiers ORDER BY fte"
    ).fetchall()
    return [(r["fte"], r["shifts_per_week"], r["shifts_per_pp"]) for r in rows]


def _load(conn, block_id):
    return (
        _load_block(conn, block_id),
        _load_staff(conn),
        _load_skills(conn),
        _load_template_needs(conn),
        _load_unavailability(conn, block_id),
        _load_closed_dates(conn),
        _load_fte_tiers(conn),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _weekday_dates(block):
    start = dt_date.fromisoformat(block["start_date"])
    end   = dt_date.fromisoformat(block["end_date"])
    d, dates = start, []
    while d <= end:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def _pay_periods(block):
    """14-day pay periods anchored to Sunday."""
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


def _week_ranges(block):
    """Mon–Fri date lists for each calendar week in the block."""
    start = dt_date.fromisoformat(block["start_date"])
    end   = dt_date.fromisoformat(block["end_date"])
    wk    = start - timedelta(days=start.weekday())
    weeks = []
    while wk <= end:
        dates = [
            (wk + timedelta(days=i)).isoformat()
            for i in range(5)
            if start <= (wk + timedelta(days=i)) <= end
        ]
        if dates:
            weeks.append(dates)
        wk += timedelta(days=7)
    return weeks


def _lookup_fte(fte_tiers, fte):
    sorted_tiers = sorted(fte_tiers, key=lambda t: t[0], reverse=True)
    for tier_fte, weekly, pp in sorted_tiers:
        if abs(tier_fte - fte) < 0.001:
            return weekly, pp
    for tier_fte, weekly, pp in sorted_tiers:
        if tier_fte <= fte:
            return weekly, pp
    return sorted_tiers[-1][1], sorted_tiers[-1][2] if sorted_tiers else (3, 5)


# ─────────────────────────────────────────────────────────────────────────────
# Optimizer
# ─────────────────────────────────────────────────────────────────────────────

def optimize(conn, block_id):
    (block, staff, skills, template_needs,
     unavailability, closed, fte_tiers) = _load(conn, block_id)

    weekday_dates = _weekday_dates(block)
    pay_periods   = _pay_periods(block)
    weeks         = _week_ranges(block)

    staff_ids  = list(staff.keys())
    skill_ids  = list(skills.keys())
    skill_name = {sid: skills[sid]["name"] for sid in skill_ids}

    # Only the TL skill is scheduled by this optimizer
    tl_skill_id = next((s for s in skill_ids if skill_name[s] == TL_SKILL), None)
    if tl_skill_id is None:
        return {"unmet": {}}, None

    # ── Pre-compute date → pay-period index and week index ────────────────────
    date_to_pp   = {}
    date_to_week = {}
    for i, (p_start, p_end) in enumerate(pay_periods):
        for d in weekday_dates:
            if p_start.isoformat() <= d <= p_end.isoformat():
                date_to_pp[d] = i
    for i, week_dates in enumerate(weeks):
        for d in week_dates:
            date_to_week[d] = i

    # ── Per-staff FTE targets and weekly maxes ────────────────────────────────
    # TL counts as a regular shift against each staff member's FTE allocation.
    # pp_targets[sid][pp_index] = max shifts allowed in that pay period,
    # capped by the number of days that staff member is actually available.
    pp_targets = {}
    week_maxes = {}
    for sid in staff_ids:
        weekly_max, pp_target = _lookup_fte(fte_tiers, staff[sid]["fte"])
        week_maxes[sid] = weekly_max
        unavail = unavailability.get(sid, set())
        pp_targets[sid] = {}
        for i, (p_start, p_end) in enumerate(pay_periods):
            avail_days = [
                d for d in weekday_dates
                if p_start.isoformat() <= d <= p_end.isoformat()
                and d not in unavail and d not in closed
            ]
            pp_targets[sid][i] = min(pp_target, len(avail_days))

    # ── Per-staff TL minimums per week ────────────────────────────────────────
    # Staff can have a minimum number of TL shifts required each week.
    tl_min_rows = conn.execute(
        "SELECT staff_id, min_per_week FROM staff_skill_minimums WHERE skill_id = ?",
        (tl_skill_id,)
    ).fetchall()
    tl_weekly_min = {r["staff_id"]: r["min_per_week"] for r in tl_min_rows}

    # ── Shift counters updated as assignments are made ────────────────────────
    pp_shift_counts   = {sid: defaultdict(int) for sid in staff_ids}
    week_shift_counts = {sid: defaultdict(int) for sid in staff_ids}
    week_tl_counts    = {sid: defaultdict(int) for sid in staff_ids}

    # ── Result structure ──────────────────────────────────────────────────────
    result      = {d: {} for d in weekday_dates}
    # assigned_tl[date] = staff_id assigned TL that day (at most 1)
    assigned_tl = {}
    # Tracks all skill assignments per person per day to prevent double-booking
    person_day_skills = defaultdict(lambda: defaultdict(set))

    # ── Sort dates by difficulty: most unavailable TL-qualified staff first ───
    # Constrained days are filled before easier days so scarce qualified staff
    # are not already consumed when the hard days are reached.
    tl_staff = [sid for sid in staff_ids if tl_skill_id in staff[sid]["skill_ids"]]

    def date_difficulty(date):
        return sum(1 for sid in tl_staff if date in unavailability.get(sid, set()))

    dates_by_difficulty = sorted(weekday_dates, key=date_difficulty, reverse=True)

    # ── Shared eligibility helpers ────────────────────────────────────────────
    def _fte_ok(sid, date):
        pp_idx   = date_to_pp.get(date)
        week_idx = date_to_week.get(date)
        if pp_idx is not None and pp_shift_counts[sid][pp_idx] >= pp_targets[sid].get(pp_idx, 0):
            return False
        if week_idx is not None and week_shift_counts[sid][week_idx] >= week_maxes[sid]:
            return False
        return True

    def _consume_shift(sid, date):
        pp_idx   = date_to_pp.get(date)
        week_idx = date_to_week.get(date)
        if pp_idx is not None:
            pp_shift_counts[sid][pp_idx] += 1
        if week_idx is not None:
            week_shift_counts[sid][week_idx] += 1

    # ── TL eligibility and assignment ─────────────────────────────────────────
    def can_assign_tl(sid, date):
        if sid not in tl_staff:
            return False
        if date in unavailability.get(sid, set()) or date in closed:
            return False
        if date in assigned_tl:
            return False
        if person_day_skills[sid][date]:
            return False
        return _fte_ok(sid, date)

    def assign_tl(sid, date):
        assigned_tl[date] = sid
        person_day_skills[sid][date].add(tl_skill_id)
        _consume_shift(sid, date)
        week_idx = date_to_week.get(date)
        if week_idx is not None:
            week_tl_counts[sid][week_idx] += 1
        result[date][TL_SKILL] = [staff[sid]["name"]]

    # ── Greedy fill: hardest days first ───────────────────────────────────────
    # For each date (sorted by how many TL-qualified staff are unavailable),
    # pick the best eligible candidate and assign them.
    for date in dates_by_difficulty:
        if date in closed:
            continue

        day_name = dt_date.fromisoformat(date).strftime("%A")
        needed   = template_needs.get(day_name, {}).get(tl_skill_id, 0)
        if needed == 0:
            continue

        # Collect eligible TL candidates for this date
        candidates = [sid for sid in tl_staff if can_assign_tl(sid, date)]

        # Sort candidates: staff who haven't met their weekly TL minimum come
        # first, then break ties by fewest TL shifts this pay period.
        week_idx = date_to_week.get(date, 0)
        pp_idx   = date_to_pp.get(date, 0)
        def candidate_key(sid):
            min_needed  = tl_weekly_min.get(sid, 0)
            below_min   = week_tl_counts[sid][week_idx] < min_needed
            return (0 if below_min else 1, pp_shift_counts[sid][pp_idx])
        candidates.sort(key=candidate_key)

        if candidates:
            assign_tl(candidates[0], date)

    # ── Shared rotation-skill helpers ─────────────────────────────────────────
    call_skill_id = next((s for s in skill_ids if skill_name[s] == "Call"), None)

    def _rotation_eligible(sid, rotation_skill_id):
        """Staff whose only schedulable skills are rotation skills + Call don't earn points."""
        return any(
            s != rotation_skill_id and s != call_skill_id
            for s in staff[sid]["skill_ids"]
        )

    def _fill_rotation_skill(skid, daily_cap, db_table, count_col, skill_label):
        """
        Generic greedy fill for a rotation skill (ECU or IRC).
        Returns {staff_id: count} for this run so the caller can persist points.
        """
        eligible_staff = [sid for sid in staff_ids if skid in staff[sid]["skill_ids"]]
        points_eligible = {sid for sid in eligible_staff if _rotation_eligible(sid, skid)}

        # Baseline points from all other blocks (excludes current block to avoid double-count)
        baseline = defaultdict(int)
        for r in conn.execute(
            f"SELECT staff_id, {count_col} FROM {db_table} WHERE block_id != ?", (block_id,)
        ).fetchall():
            baseline[r["staff_id"]] += r[count_col]

        this_run = defaultdict(int)
        day_counts = defaultdict(int)  # date → slots filled so far

        dates_sorted = sorted(
            weekday_dates,
            key=lambda d: sum(1 for sid in eligible_staff if d in unavailability.get(sid, set())),
            reverse=True,
        )

        def can_assign(sid, date):
            if date in unavailability.get(sid, set()) or date in closed:
                return False
            if person_day_skills[sid][date]:
                return False
            if day_counts[date] >= daily_cap:
                return False
            return _fte_ok(sid, date)

        for date in dates_sorted:
            if date in closed:
                continue
            day_name  = dt_date.fromisoformat(date).strftime("%A")
            needed    = template_needs.get(day_name, {}).get(skid, 0)
            remaining = needed - len(result[date].get(skill_label, []))
            if remaining <= 0:
                continue

            candidates = [sid for sid in eligible_staff if can_assign(sid, date)]
            pp_idx = date_to_pp.get(date, 0)
            candidates.sort(key=lambda sid: (
                baseline[sid] + this_run[sid],
                pp_shift_counts[sid][pp_idx],
            ))

            for sid in candidates[:remaining]:
                day_counts[date] += 1
                person_day_skills[sid][date].add(skid)
                _consume_shift(sid, date)
                if sid in points_eligible:
                    this_run[sid] += 1
                result[date].setdefault(skill_label, []).append(staff[sid]["name"])

        # Persist — replace any previous run for this block
        with conn:
            conn.execute(f"DELETE FROM {db_table} WHERE block_id = ?", (block_id,))
            for sid, count in this_run.items():
                if count > 0:
                    conn.execute(
                        f"INSERT INTO {db_table} (block_id, staff_id, {count_col}) VALUES (?, ?, ?)",
                        (block_id, sid, count)
                    )
            conn.commit()

        return this_run

    # ── ECU fill ──────────────────────────────────────────────────────────────
    ecu_skill_id = next((s for s in skill_ids if skill_name[s] == ECU_SKILL), None)
    if ecu_skill_id is not None:
        _fill_rotation_skill(ecu_skill_id, ECU_DAILY_CAP,
                             "ecu_block_assignments", "ecu_count", ECU_SKILL)

    # ── IRC fill ──────────────────────────────────────────────────────────────
    irc_skill_id = next((s for s in skill_ids if skill_name[s] == IRC_SKILL), None)
    if irc_skill_id is not None:
        _fill_rotation_skill(irc_skill_id, IRC_DAILY_CAP,
                             "irc_block_assignments", "irc_count", IRC_SKILL)

    # ── IR RN fill ────────────────────────────────────────────────────────────
    # Two-pass approach (both passes use hardest-days-first order):
    #   Pass 1 — fill each day to 3, picking the most-underutilized staff first.
    #   Pass 2 — continue assigning to staff still below their FTE target;
    #             no daily cap in this pass.
    ir_rn_skill_id = next((s for s in skill_ids if skill_name[s] == IR_RN_SKILL), None)
    if ir_rn_skill_id is not None:
        IR_RN_PASS1_TARGET = 3

        ir_rn_staff = [sid for sid in staff_ids if ir_rn_skill_id in staff[sid]["skill_ids"]]

        # Hardest days first: most unavailable IR RN-qualified staff
        ir_rn_dates = sorted(
            weekday_dates,
            key=lambda d: sum(1 for sid in ir_rn_staff if d in unavailability.get(sid, set())),
            reverse=True,
        )

        def can_assign_ir_rn(sid, date):
            if date in unavailability.get(sid, set()) or date in closed:
                return False
            if person_day_skills[sid][date]:
                return False
            return _fte_ok(sid, date)

        # Staff closest to their FTE target go last; furthest below go first.
        # Sort key: pp_shift_counts - pp_target  (most negative = most underutilized)
        def ir_rn_sort(sid, date):
            pp_idx = date_to_pp.get(date, 0)
            return pp_shift_counts[sid][pp_idx] - pp_targets[sid].get(pp_idx, 0)

        ir_rn_day_counts = defaultdict(int)
        ir_rn_assigned   = defaultdict(set)  # date → set of staff_ids

        def assign_ir_rn(sid, date):
            person_day_skills[sid][date].add(ir_rn_skill_id)
            _consume_shift(sid, date)
            ir_rn_assigned[date].add(sid)
            ir_rn_day_counts[date] += 1
            result[date].setdefault(IR_RN_SKILL, []).append(staff[sid]["name"])

        def unassign_ir_rn(sid, date):
            person_day_skills[sid][date].discard(ir_rn_skill_id)
            ir_rn_assigned[date].discard(sid)
            ir_rn_day_counts[date] -= 1
            pp_idx   = date_to_pp.get(date)
            week_idx = date_to_week.get(date)
            if pp_idx is not None:
                pp_shift_counts[sid][pp_idx] -= 1
            if week_idx is not None:
                week_shift_counts[sid][week_idx] -= 1
            name = staff[sid]["name"]
            result[date][IR_RN_SKILL] = [n for n in result[date].get(IR_RN_SKILL, []) if n != name]
            if not result[date].get(IR_RN_SKILL):
                result[date].pop(IR_RN_SKILL, None)

        def can_move_ir_rn(sid, from_date, to_date):
            """Check if sid can be moved from from_date to to_date."""
            if to_date in unavailability.get(sid, set()) or to_date in closed:
                return False
            if person_day_skills[sid][to_date]:
                return False
            # Same week → week count is net-zero; only check cross-PP moves
            from_pp = date_to_pp.get(from_date)
            to_pp   = date_to_pp.get(to_date)
            if from_pp != to_pp and to_pp is not None:
                if pp_shift_counts[sid][to_pp] >= pp_targets[sid].get(to_pp, 0):
                    return False
            return True

        # Pass 1: target 3 per day, hardest days first
        for date in ir_rn_dates:
            if date in closed:
                continue
            remaining = IR_RN_PASS1_TARGET - ir_rn_day_counts[date]
            if remaining <= 0:
                continue
            candidates = sorted(
                [sid for sid in ir_rn_staff if can_assign_ir_rn(sid, date)],
                key=lambda sid: ir_rn_sort(sid, date),
            )
            for sid in candidates[:remaining]:
                assign_ir_rn(sid, date)

        # Pass 2: assign remaining FTE capacity — no daily cap
        for date in ir_rn_dates:
            if date in closed:
                continue
            candidates = sorted(
                [sid for sid in ir_rn_staff
                 if can_assign_ir_rn(sid, date) and ir_rn_sort(sid, date) < 0],
                key=lambda sid: ir_rn_sort(sid, date),
            )
            for sid in candidates:
                assign_ir_rn(sid, date)

        # Pass 3: within-week rebalancing toward 5 per day.
        # Move IR RN assignments from over-staffed days to under-staffed days
        # within the same calendar week so no day exceeds FTE constraints.
        IR_RN_PASS3_TARGET = 5
        for week_dates in weeks:
            work_days = [d for d in week_dates if d not in closed]
            if len(work_days) < 2:
                continue

            # Iterate until no further improvement is possible
            moved = True
            while moved:
                moved = False
                # Sort: most under-staffed first, most over-staffed last
                by_count = sorted(work_days, key=lambda d: ir_rn_day_counts[d])
                under_days = [d for d in by_count if ir_rn_day_counts[d] < IR_RN_PASS3_TARGET]
                over_days  = sorted(
                    [d for d in by_count if ir_rn_day_counts[d] > IR_RN_PASS3_TARGET],
                    key=lambda d: ir_rn_day_counts[d], reverse=True
                )

                for under_date in under_days:
                    for over_date in over_days:
                        if ir_rn_day_counts[over_date] <= ir_rn_day_counts[under_date]:
                            continue
                        # Find a staff member assigned on over_date who can work under_date
                        movable = [
                            sid for sid in ir_rn_assigned[over_date]
                            if can_move_ir_rn(sid, over_date, under_date)
                        ]
                        if movable:
                            sid = movable[0]
                            unassign_ir_rn(sid, over_date)
                            assign_ir_rn(sid, under_date)
                            moved = True
                            break  # restart the while loop with fresh counts
                    if moved:
                        break

    # ── IR Late fill ──────────────────────────────────────────────────────────
    # IR Late can only go to staff who are already assigned TL, IRC, or IR RN
    # on that day.  It is a late-shift extension so it does not consume FTE.
    # Fairness point system identical to ECU/IRC.
    ir_late_skill_id = next((s for s in skill_ids if skill_name[s] == IR_LATE_SKILL), None)
    if ir_late_skill_id is not None:
        ir_late_staff = [sid for sid in staff_ids if ir_late_skill_id in staff[sid]["skill_ids"]]

        # Skills that qualify a person as "already working" that day
        qualifying_skids = {s for s in [tl_skill_id, irc_skill_id, ir_rn_skill_id] if s is not None}

        # Points eligibility: same rule as ECU/IRC
        ir_late_points_eligible = {sid for sid in ir_late_staff if _rotation_eligible(sid, ir_late_skill_id)}

        # Baseline points from all other blocks
        ir_late_baseline = defaultdict(int)
        for r in conn.execute(
            "SELECT staff_id, ir_late_count FROM ir_late_block_assignments WHERE block_id != ?",
            (block_id,)
        ).fetchall():
            ir_late_baseline[r["staff_id"]] += r["ir_late_count"]

        ir_late_this_run   = defaultdict(int)
        ir_late_day_assigned = defaultdict(set)  # date → staff_ids assigned IR Late

        # Hardest days first: most unavailable IR-Late-qualified staff
        ir_late_dates = sorted(
            weekday_dates,
            key=lambda d: sum(1 for sid in ir_late_staff if d in unavailability.get(sid, set())),
            reverse=True,
        )

        def can_assign_ir_late(sid, date):
            if date in unavailability.get(sid, set()) or date in closed:
                return False
            # Must already be scheduled for a qualifying shift this day
            if not (person_day_skills[sid][date] & qualifying_skids):
                return False
            # Not already assigned IR Late on this day
            return sid not in ir_late_day_assigned[date]

        for date in ir_late_dates:
            if date in closed:
                continue
            day_name  = dt_date.fromisoformat(date).strftime("%A")
            needed    = template_needs.get(day_name, {}).get(ir_late_skill_id, 0)
            remaining = needed - len(ir_late_day_assigned[date])
            if remaining <= 0:
                continue

            candidates = [sid for sid in ir_late_staff if can_assign_ir_late(sid, date)]
            pp_idx = date_to_pp.get(date, 0)
            candidates.sort(key=lambda sid: (
                ir_late_baseline[sid] + ir_late_this_run[sid],
                pp_shift_counts[sid][pp_idx],
            ))

            for sid in candidates[:remaining]:
                ir_late_day_assigned[date].add(sid)
                if sid in ir_late_points_eligible:
                    ir_late_this_run[sid] += 1
                result[date].setdefault(IR_LATE_SKILL, []).append(staff[sid]["name"])

        # Persist — replace previous run for this block
        with conn:
            conn.execute("DELETE FROM ir_late_block_assignments WHERE block_id = ?", (block_id,))
            for sid, count in ir_late_this_run.items():
                if count > 0:
                    conn.execute(
                        "INSERT INTO ir_late_block_assignments (block_id, staff_id, ir_late_count)"
                        " VALUES (?, ?, ?)",
                        (block_id, sid, count)
                    )
            conn.commit()

    # ── Compute unmet needs (TL + ECU + IRC) ─────────────────────────────────
    skill_checks = [(tl_skill_id, TL_SKILL)]
    if ecu_skill_id is not None:
        skill_checks.append((ecu_skill_id, ECU_SKILL))
    if irc_skill_id is not None:
        skill_checks.append((irc_skill_id, IRC_SKILL))
    if ir_rn_skill_id is not None:
        skill_checks.append((ir_rn_skill_id, IR_RN_SKILL))
    if ir_late_skill_id is not None:
        skill_checks.append((ir_late_skill_id, IR_LATE_SKILL))

    unmet = {}
    for date in weekday_dates:
        if date in closed:
            continue
        day_name  = dt_date.fromisoformat(date).strftime("%A")
        day_unmet = {
            label: needed - len(result[date].get(label, []))
            for skid, label in skill_checks
            for needed in [template_needs.get(day_name, {}).get(skid, 0)]
            if needed > len(result[date].get(label, []))
        }
        if day_unmet:
            unmet[date] = day_unmet

    result["unmet"] = unmet
    return result, None


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    result, error = optimize(conn, block_id=1)
    conn.close()
    if error:
        print("Error:", error)
    else:
        unmet = result.pop("unmet", {})
        for date in sorted(result.keys()):
            day = result[date]
            if not day:
                continue
            print(f"\n{date} ({dt_date.fromisoformat(date).strftime('%A')})")
            for skill, names in day.items():
                print(f"  {skill}: {', '.join(names)}")
        print("\n--- Unmet ---")
        if unmet:
            for date, day_unmet in sorted(unmet.items()):
                for skill, count in day_unmet.items():
                    print(f"  {date} {skill}: {count} short")
        else:
            print("  None")
