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
                "id":     s["id"],
                "name":   s["name"],
                "fte":    s["fte"],
                "skills": [{"id": sk["id"], "name": sk["name"]} for sk in skills],
            })
    return jsonify(result)


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


def _fte_target(fte):
    if fte >= 1.0:  return 8
    if fte >= 0.75: return 6
    return 5  # 0.6 FTE


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
        target = _fte_target(s["fte"])

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


@bp.route("/blocks/<int:block_id>/publish", methods=["POST"])
def publish_block(block_id):
    """
    Publish a block: copy optimized schedule to the calendar events
    and mark the block as published.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM optimized_schedule WHERE block_id = ?", (block_id,)
        ).fetchone()
        if not row or not row["result_json"]:
            return jsonify({"error": "No optimized schedule found. Run optimizer first."}), 422

        conn.execute(
            "UPDATE schedule_blocks SET status='published' WHERE id=?", (block_id,)
        )
        conn.commit()

    return jsonify({"ok": True})


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