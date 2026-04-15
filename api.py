import json
from datetime import date as dt_date, timedelta
from flask import Blueprint, jsonify, request
from database import get_db

bp = Blueprint("api", __name__, url_prefix="/api")

CALL_SKILL_NAME = "Call"


# ── Schedule events (existing calendar) ─────────────────────────────────────

@bp.route("/schedule/events")
def schedule_events():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM generated_schedule WHERE id = 1").fetchone()

    if not row or not row["result_json"]:
        return jsonify([])

    result = json.loads(row["result_json"])
    result.pop("unmet", None)

    events = []
    for date_str, skills in result.items():
        if not skills:
            continue
        for skill_name, names in skills.items():
            if not names:
                continue
            events.append({
                "title": f"{skill_name}: {', '.join(names)}",
                "start": date_str,
                "end":   date_str,
                "skill": skill_name,
                "staff": names,
            })
    return jsonify(events)


@bp.route("/schedule/meta")
def schedule_meta():
    with get_db() as conn:
        row = conn.execute(
            "SELECT month_start, generated_at FROM generated_schedule WHERE id = 1"
        ).fetchone()
    if not row:
        return jsonify({"month_start": None, "generated_at": None})
    return jsonify({"month_start": row["month_start"], "generated_at": row["generated_at"]})


# ── Blocks ───────────────────────────────────────────────────────────────────

@bp.route("/blocks")
def get_blocks():
    with get_db() as conn:
        blocks = conn.execute(
            "SELECT * FROM schedule_blocks ORDER BY start_date DESC"
        ).fetchall()
    return jsonify([dict(b) for b in blocks])


@bp.route("/blocks", methods=["POST"])
def create_block():
    from datetime import timedelta
    data       = request.get_json()
    name       = data.get("name", "").strip()
    start_date = data.get("start_date", "").strip()
    if not name or not start_date:
        return jsonify({"error": "name and start_date required"}), 400
    start = dt_date.fromisoformat(start_date)
    end   = start + timedelta(weeks=8) - timedelta(days=1)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO schedule_blocks (name, start_date, end_date) VALUES (?, ?, ?)",
            (name, start.isoformat(), end.isoformat())
        )
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/blocks/<int:block_id>")
def get_block(block_id):
    with get_db() as conn:
        block = conn.execute(
            "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
        ).fetchone()
        if not block:
            return jsonify({"error": "not found"}), 404
    return jsonify(dict(block))


@bp.route("/blocks/<int:block_id>", methods=["DELETE"])
def delete_block(block_id):
    with get_db() as conn:
        conn.execute("DELETE FROM schedule_blocks WHERE id = ?", (block_id,))
        conn.commit()
    return jsonify({"ok": True})


# ── Staff & Skills ───────────────────────────────────────────────────────────

@bp.route("/staff")
def get_staff():
    with get_db() as conn:
        staff_rows = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
        result = []
        for s in staff_rows:
            skills = conn.execute("""
                SELECT sk.id, sk.name FROM skills sk
                JOIN staff_skills ss ON sk.id = ss.skill_id
                WHERE ss.staff_id = ?
                ORDER BY sk.name
            """, (s["id"],)).fetchall()
            result.append({
                "id":        s["id"],
                "name":      s["name"],
                "fte":       s["fte"],
                "is_casual": bool(s["is_casual"]),
                "skills":    [{"id": sk["id"], "name": sk["name"]} for sk in skills],
            })
    return jsonify(result)


@bp.route("/staff", methods=["POST"])
def create_staff():
    data = request.get_json()
    name      = (data.get("name") or "").strip()
    skill_ids = data.get("skill_ids", [])
    is_casual = bool(data.get("is_casual", False))
    if not name:
        return jsonify({"error": "Name is required"}), 400
    fte = 1.0
    if not is_casual:
        try:
            fte = float(data.get("fte", 1.0))
            if not (0.0 < fte <= 1.0):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid FTE value"}), 400
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO staff (name, fte, is_casual) VALUES (?, ?, ?)",
            (name, fte, int(is_casual))
        )
        staff_id = cur.lastrowid
        for sid in skill_ids:
            conn.execute("INSERT INTO staff_skills (staff_id, skill_id) VALUES (?, ?)", (staff_id, sid))
        conn.commit()
    return jsonify({"ok": True, "id": staff_id})


@bp.route("/staff/<int:staff_id>", methods=["PUT"])
def update_staff(staff_id):
    data      = request.get_json()
    name      = (data.get("name") or "").strip()
    skill_ids = data.get("skill_ids", [])
    is_casual = bool(data.get("is_casual", False))
    if not name:
        return jsonify({"error": "Name is required"}), 400
    fte = 1.0
    if not is_casual:
        try:
            fte = float(data.get("fte", 1.0))
            if not (0.0 < fte <= 1.0):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid FTE value"}), 400
    with get_db() as conn:
        conn.execute(
            "UPDATE staff SET name=?, fte=?, is_casual=? WHERE id=?",
            (name, fte, int(is_casual), staff_id)
        )
        conn.execute("DELETE FROM staff_skills WHERE staff_id=?", (staff_id,))
        for sid in skill_ids:
            conn.execute("INSERT INTO staff_skills (staff_id, skill_id) VALUES (?, ?)", (staff_id, sid))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/staff/<int:staff_id>", methods=["DELETE"])
def delete_staff(staff_id):
    with get_db() as conn:
        conn.execute("DELETE FROM staff WHERE id=?", (staff_id,))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/skills")
def get_skills():
    with get_db() as conn:
        skills = conn.execute("SELECT * FROM skills ORDER BY priority, name").fetchall()
    return jsonify([dict(s) for s in skills])


# ── Template needs (slot targets) ────────────────────────────────────────────

@bp.route("/template/needs")
def get_template_needs():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT tn.day_of_week, tn.skill_id, tn.quantity, sk.name as skill_name
            FROM template_needs tn
            JOIN skills sk ON sk.id = tn.skill_id
            WHERE tn.template_id = 1
        """).fetchall()
    needs = {}
    for row in rows:
        needs.setdefault(row["day_of_week"], {})[row["skill_id"]] = {
            "quantity":   row["quantity"],
            "skill_name": row["skill_name"],
        }
    return jsonify(needs)


# ── Block requests ───────────────────────────────────────────────────────────

@bp.route("/blocks/<int:block_id>/requests")
def get_requests(block_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT sr.staff_id, sr.date, sr.skill_id, sk.name as skill_name,
                   st.name as staff_name
            FROM staff_requests sr
            JOIN skills sk ON sk.id = sr.skill_id
            JOIN staff st  ON st.id = sr.staff_id
            WHERE sr.block_id = ?
        """, (block_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/blocks/<int:block_id>/requests", methods=["POST"])
def set_request(block_id):
    data     = request.get_json()
    staff_id = data.get("staff_id")
    date     = data.get("date")
    skill_id = data.get("skill_id")

    if not all([staff_id, date, skill_id]):
        return jsonify({"error": "staff_id, date, skill_id required"}), 400

    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO staff_requests (block_id, staff_id, date, skill_id)
            VALUES (?, ?, ?, ?)
        """, (block_id, staff_id, date, skill_id))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/blocks/<int:block_id>/requests/delete", methods=["POST"])
def delete_request(block_id):
    data     = request.get_json()
    staff_id = data.get("staff_id")
    date     = data.get("date")
    skill_id = data.get("skill_id")

    with get_db() as conn:
        conn.execute("""
            DELETE FROM staff_requests
            WHERE block_id = ? AND staff_id = ? AND date = ? AND skill_id = ?
        """, (block_id, staff_id, date, skill_id))
        conn.commit()
    return jsonify({"ok": True})


# ── FTE validation ───────────────────────────────────────────────────────────

def _pay_periods(block_start_str, block_end_str):
    """Return list of (start, end) date tuples for each 2-week pay period."""
    block_start  = dt_date.fromisoformat(block_start_str)
    block_end    = dt_date.fromisoformat(block_end_str)
    days_back    = (block_start.weekday() + 1) % 7  # back to Sunday
    period_start = block_start - timedelta(days=days_back)
    periods = []
    while period_start <= block_end:
        period_end = period_start + timedelta(days=13)
        periods.append((period_start, period_end))
        period_start = period_end + timedelta(days=1)
    return periods


def _fte_target(fte, tier_rows):
    """Look up shifts-per-pay-period for the given FTE from preloaded tier rows."""
    for row in tier_rows:          # rows ordered DESC by fte
        if abs(row["fte"] - fte) < 0.001:
            return row["shifts_per_pp"]
    for row in tier_rows:
        if row["fte"] <= fte:
            return row["shifts_per_pp"]
    return tier_rows[-1]["shifts_per_pp"] if tier_rows else 5


# ── FTE tiers ─────────────────────────────────────────────────────────────────

@bp.route("/fte-tiers")
def get_fte_tiers():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT fte, shifts_per_week, shifts_per_pp FROM fte_tiers ORDER BY fte"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/fte-tiers", methods=["POST"])
def create_fte_tier():
    data = request.get_json()
    try:
        fte    = round(float(data["fte"]), 4)
        weekly = int(data["shifts_per_week"])
        pp     = int(data["shifts_per_pp"])
        if not (0.0 < fte <= 1.0) or weekly < 1 or pp < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid data"}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT INTO fte_tiers (fte, shifts_per_week, shifts_per_pp) VALUES (?, ?, ?)",
            (fte, weekly, pp)
        )
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/fte-tiers/<fte_str>", methods=["PUT"])
def update_fte_tier(fte_str):
    data = request.get_json()
    try:
        fte    = round(float(fte_str), 4)
        weekly = int(data["shifts_per_week"])
        pp     = int(data["shifts_per_pp"])
        if weekly < 1 or pp < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid data"}), 400
    with get_db() as conn:
        conn.execute(
            "UPDATE fte_tiers SET shifts_per_week=?, shifts_per_pp=? WHERE fte=?",
            (weekly, pp, fte)
        )
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/fte-tiers/<fte_str>", methods=["DELETE"])
def delete_fte_tier(fte_str):
    try:
        fte = round(float(fte_str), 4)
    except ValueError:
        return jsonify({"error": "Invalid FTE"}), 400
    with get_db() as conn:
        conn.execute("DELETE FROM fte_tiers WHERE fte=?", (fte,))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/blocks/<int:block_id>/validate_fte")
def validate_fte(block_id):
    with get_db() as conn:
        block = conn.execute(
            "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
        ).fetchone()
        if not block:
            return jsonify({"error": "not found"}), 404

        staff_rows = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
        requests   = conn.execute(
            "SELECT staff_id, date FROM staff_requests WHERE block_id = ?", (block_id,)
        ).fetchall()
        unavail    = conn.execute(
            "SELECT staff_id, date FROM staff_unavailability WHERE block_id = ?", (block_id,)
        ).fetchall()
        fte_tier_rows = conn.execute(
            "SELECT fte, shifts_per_pp FROM fte_tiers ORDER BY fte DESC"
        ).fetchall()

    worked = {}
    off    = {}
    for r in requests:
        worked.setdefault(r["staff_id"], set()).add(r["date"])
    for u in unavail:
        off.setdefault(u["staff_id"], set()).add(u["date"])

    periods  = _pay_periods(block["start_date"], block["end_date"])
    warnings = []

    for s in staff_rows:
        sid    = s["id"]
        target = _fte_target(s["fte"], fte_tier_rows)

        for i, (p_start, p_end) in enumerate(periods):
            # Collect Mon–Fri dates in this pay period
            weekdays = set()
            d = p_start
            while d <= p_end:
                if d.weekday() < 5:
                    weekdays.add(d.isoformat())
                d += timedelta(days=1)

            shifts    = len(worked.get(sid, set()) & weekdays)
            unavail_c = len(off.get(sid, set())    & weekdays)
            total     = shifts + unavail_c
            label     = (f"pay period {i+1} "
                         f"({p_start.strftime('%m/%d')}–{p_end.strftime('%m/%d')})")

            if total > target:
                warnings.append({
                    "type":    "over",
                    "staff":   s["name"],
                    "message": f"{s['name']} is over FTE in {label} ({total}/{target})"
                })
            elif total < target:
                warnings.append({
                    "type":    "under",
                    "staff":   s["name"],
                    "message": f"{s['name']} is under FTE in {label} ({total}/{target})"
                })

    return jsonify({"warnings": warnings})

@bp.route("/blocks/<int:block_id>/unavailability")
def get_unavailability(block_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT su.staff_id, su.date, st.name as staff_name
            FROM staff_unavailability su
            JOIN staff st ON st.id = su.staff_id
            WHERE su.block_id = ?
        """, (block_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/blocks/<int:block_id>/unavailability", methods=["POST"])
def add_unavailability(block_id):
    data     = request.get_json()
    staff_id = data.get("staff_id")
    date     = data.get("date")
    if not all([staff_id, date]):
        return jsonify({"error": "staff_id and date required"}), 400
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO staff_unavailability (block_id, staff_id, date)
            VALUES (?, ?, ?)
        """, (block_id, staff_id, date))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/blocks/<int:block_id>/unavailability/delete", methods=["POST"])
def delete_unavailability(block_id):
    data     = request.get_json()
    staff_id = data.get("staff_id")
    date     = data.get("date")
    with get_db() as conn:
        conn.execute("""
            DELETE FROM staff_unavailability
            WHERE block_id = ? AND staff_id = ? AND date = ?
        """, (block_id, staff_id, date))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/blocks/<int:block_id>/events")
def get_block_events(block_id):
    """
    Return events for a block. If an optimized schedule exists, use that.
    Otherwise fall back to raw staff requests.
    """
    with get_db() as conn:
        opt_row = conn.execute(
            "SELECT result_json FROM optimized_schedule WHERE block_id = ?", (block_id,)
        ).fetchone()

        if opt_row and opt_row["result_json"]:
            result = json.loads(opt_row["result_json"])
            result.pop("unmet", None)
            events = []
            for date_str, day in result.items():
                for skill_name, names in day.items():
                    if not names:
                        continue
                    events.append({
                        "title": f"{skill_name}: {', '.join(names)}",
                        "start": date_str,
                        "end":   date_str,
                        "skill": skill_name,
                        "staff": names,
                        "source": "optimized",
                    })
            return jsonify(events)

        # Fall back to raw requests
        rows = conn.execute("""
            SELECT sr.date, sk.name as skill_name, st.name as staff_name
            FROM staff_requests sr
            JOIN skills sk ON sk.id = sr.skill_id
            JOIN staff st  ON st.id = sr.staff_id
            WHERE sr.block_id = ?
            ORDER BY sr.date, sk.name, st.name
        """, (block_id,)).fetchall()

    grouped = {}
    for row in rows:
        key = (row["date"], row["skill_name"])
        grouped.setdefault(key, []).append(row["staff_name"])

    events = []
    for (date_str, skill_name), names in grouped.items():
        events.append({
            "title": f"{skill_name}: {', '.join(names)}",
            "start": date_str,
            "end":   date_str,
            "skill": skill_name,
            "staff": names,
            "source": "requests",
        })
    return jsonify(events)


# ── Optimize & Publish ───────────────────────────────────────────────────────

@bp.route("/blocks/<int:block_id>/optimize", methods=["POST"])
def run_optimize(block_id):
    """Run the OR-Tools optimizer for a block and store the result."""
    try:
        from optimizer import optimize
    except ImportError:
        return jsonify({"error": "OR-Tools not installed. Run: pip install ortools"}), 500

    with get_db() as conn:
        block = conn.execute(
            "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
        ).fetchone()
        if not block:
            return jsonify({"error": "Block not found"}), 404

        result, error = optimize(conn, block_id)

        if error:
            return jsonify({"error": error}), 422

        conn.execute("""
            INSERT INTO optimized_schedule (block_id, result_json, optimized_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(block_id) DO UPDATE SET
                result_json  = excluded.result_json,
                optimized_at = excluded.optimized_at
        """, (block_id, json.dumps(result)))
        conn.commit()

    return jsonify({"ok": True, "message": "Schedule optimized successfully."})


@bp.route("/blocks/<int:block_id>/optimized")
def get_optimized(block_id):
    """Return the optimized schedule result for a block."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM optimized_schedule WHERE block_id = ?", (block_id,)
        ).fetchone()

    if not row or not row["result_json"]:
        return jsonify({"result": None, "optimized_at": None})

    result = json.loads(row["result_json"])
    unmet  = result.pop("unmet", {})
    return jsonify({
        "result":       result,
        "unmet":        unmet,
        "optimized_at": row["optimized_at"],
    })


@bp.route("/blocks/<int:block_id>/accept_optimized", methods=["POST"])
def accept_optimized(block_id):
    """Replace staff_requests with optimizer output. The optimizer output is the new grid."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT result_json FROM optimized_schedule WHERE block_id = ?", (block_id,)
        ).fetchone()
        if not row or not row["result_json"]:
            return jsonify({"error": "No optimized schedule found"}), 422

        result = json.loads(row["result_json"])
        result.pop("unmet", None)

        skills = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM skills").fetchall()}
        staff  = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM staff").fetchall()}

        # Replace all non-Call requests with optimizer output; Call is managed manually
        conn.execute("""
            DELETE FROM staff_requests
            WHERE block_id = ?
              AND skill_id NOT IN (SELECT id FROM skills WHERE name = 'Call')
        """, (block_id,))

        added = 0
        for date_str, day in result.items():
            for skill_name, names in day.items():
                skill_id = skills.get(skill_name)
                if not skill_id:
                    continue
                for name in names:
                    staff_id = staff.get(name)
                    if not staff_id:
                        continue
                    conn.execute("""
                        INSERT INTO staff_requests (block_id, staff_id, date, skill_id)
                        VALUES (?, ?, ?, ?)
                    """, (block_id, staff_id, date_str, skill_id))
                    added += 1

        conn.commit()

    return jsonify({"ok": True, "added": added})

@bp.route('/blocks/<int:block_id>/publish', methods=['POST'])
def publish_block(block_id):
    with get_db() as conn:
        block = conn.execute(
            "SELECT * FROM schedule_blocks WHERE id=?", (block_id,)
        ).fetchone()
        if not block:
            return jsonify({"error": "Block not found"}), 404

        # Build current snapshot from staff_requests
        req_rows = conn.execute("""
            SELECT sr.date, sk.name AS skill_name, st.name AS staff_name
            FROM staff_requests sr
            JOIN skills sk ON sk.id = sr.skill_id
            JOIN staff   st ON st.id = sr.staff_id
            WHERE sr.block_id = ?
            ORDER BY sr.date, sk.name, st.name
        """, (block_id,)).fetchall()

        current: dict = {}
        for r in req_rows:
            current.setdefault(r["date"], {}).setdefault(r["skill_name"], []).append(r["staff_name"])

        # Compare against last published snapshot (if any)
        last_pub = conn.execute(
            "SELECT snapshot_json FROM block_last_published WHERE block_id=?", (block_id,)
        ).fetchone()

        changes_json = None
        is_republish = last_pub is not None

        if is_republish:
            old: dict = json.loads(last_pub["snapshot_json"])

            def to_tuples(snap):
                return {
                    (date, skill, name)
                    for date, skills in snap.items()
                    for skill, names in skills.items()
                    for name in names
                }

            old_set = to_tuples(old)
            new_set = to_tuples(current)
            changes = (
                [{"type": "added",   "date": d, "skill": sk, "staff": st} for d, sk, st in sorted(new_set - old_set)]
              + [{"type": "removed", "date": d, "skill": sk, "staff": st} for d, sk, st in sorted(old_set - new_set)]
            )
            changes.sort(key=lambda c: (c["date"], c["skill"], c["type"]))
            changes_json = json.dumps(changes)

        # Next version number
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM block_publish_history WHERE block_id=?",
            (block_id,)
        ).fetchone()
        version = row["v"] + 1

        conn.execute(
            "INSERT INTO block_publish_history (block_id, version, changes_json) VALUES (?, ?, ?)",
            (block_id, version, changes_json)
        )
        conn.execute("""
            INSERT INTO block_last_published (block_id, snapshot_json)
            VALUES (?, ?)
            ON CONFLICT(block_id) DO UPDATE SET
                snapshot_json = excluded.snapshot_json,
                published_at  = datetime('now')
        """, (block_id, json.dumps(current)))
        conn.execute("UPDATE schedule_blocks SET status='published' WHERE id=?", (block_id,))
        conn.commit()

    return jsonify({"ok": True, "version": version, "is_republish": is_republish})


@bp.route('/blocks/<int:block_id>/publish-history')
def get_publish_history(block_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, version, published_at, changes_json
            FROM block_publish_history
            WHERE block_id = ?
            ORDER BY version DESC
        """, (block_id,)).fetchall()
    return jsonify([{
        "id":           r["id"],
        "version":      r["version"],
        "published_at": r["published_at"],
        "changes":      json.loads(r["changes_json"]) if r["changes_json"] else None,
    } for r in rows])


@bp.route("/blocks/<int:block_id>/optimized/events")
def get_optimized_events(block_id):
    """Return optimized schedule as calendar events."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM optimized_schedule WHERE block_id = ?", (block_id,)
        ).fetchone()

    if not row or not row["result_json"]:
        return jsonify([])

    result = json.loads(row["result_json"])
    result.pop("unmet", None)

    events = []
    for date_str, day in result.items():
        for skill_name, names in day.items():
            if not names:
                continue
            events.append({
                "title": f"{skill_name}: {', '.join(names)}",
                "start": date_str,
                "end":   date_str,
                "skill": skill_name,
                "staff": names,
            })
    return jsonify(events)


# ── Test Runner ──────────────────────────────────────────────────────────────

@bp.route("/run_tests", methods=["POST"])
def run_tests():
    """Run the adversarial test suite and return results as JSON."""
    import sys, os, io, contextlib
    from datetime import date as dt_date, timedelta
    from collections import defaultdict

    # Capture all output
    output_buffer = io.StringIO()
    tests   = []
    current = None
    r       = {"passed": 0, "failed": 0, "warned": 0}

    def check(name, condition, detail=""):
        status = "pass" if condition else "fail"
        text   = name + (f": {detail}" if detail and not condition else "")
        label  = "PASS" if condition else "FAIL"
        line   = f"  {label} {text}"
        output_buffer.write(line + "\n")
        if current is not None:
            current["checks"].append({"status": status, "text": text})
        if condition:
            r["passed"] += 1
        else:
            r["failed"] += 1

    def warn(name, detail=""):
        text = name + (f": {detail}" if detail else "")
        output_buffer.write(f"  WARN {text}\n")
        if current is not None:
            current["checks"].append({"status": "warn", "text": text})
        r["warned"] += 1

    def section(title):
        nonlocal current
        if current is not None:
            tests.append(current)
        current = {"section": title, "checks": []}
        output_buffer.write(f"\n-- {title}\n")

    def run_opt(conn, block_id=1, time_limit=25):
        from optimizer import optimize
        import sys, os
        devnull = open(os.devnull, 'w')
        old_stderr = sys.stderr
        sys.stderr = devnull
        try:
            return optimize(conn, block_id, time_limit_seconds=time_limit)
        finally:
            sys.stderr = old_stderr
            devnull.close()

    # Import helpers from test_adversarial
    try:
        import test_adversarial as ta
    except ImportError:
        return jsonify({"error": "test_adversarial.py not found in app directory"}), 404

    # Override test_adversarial's globals with our capturing versions
    ta.check        = check
    ta.warn         = warn
    ta.section      = section
    ta.run_optimizer = run_opt
    ta.results      = r

    try:
        ta.test_zero_slack()
        ta.test_staff_unavailable_entire_block()
        ta.test_entire_pay_period_unavailable()
        ta.test_two_staff_same_week_unavailable()
        ta.test_block_starts_friday()
        ta.test_block_starts_sunday()
        ta.test_only_one_tl_available()
        ta.test_minimum_exceeds_qualified_staff()
        ta.test_all_ecu_only_staff_unavailable()
        ta.test_negative_required_shifts()
        ta.test_fte_already_full_via_requests()
        ta.test_all_staff_point_six_fte()
        ta.test_multiple_optimizer_runs()
        ta.test_rotation_history_affects_next_block()
        ta.test_future_rotation_history()
        ta.test_staff_with_no_skills()
        ta.test_closed_date_in_middle()
        ta.test_zero_quantity_template_need()
        ta.test_all_days_closed()
        ta.test_request_for_unqualified_skill()
        ta.test_request_on_unavailable_day()
        ta.test_two_staff_request_same_tl_slot()
        ta.test_requests_exceed_fte()
    except Exception as e:
        import traceback
        output_buffer.write(f"\nUnhandled error: {traceback.format_exc()}\n")

    if current is not None:
        tests.append(current)

    return jsonify({
        "tests":  tests,
        "passed": r["passed"],
        "failed": r["failed"],
        "warned": r["warned"],
        "raw":    output_buffer.getvalue(),
    })