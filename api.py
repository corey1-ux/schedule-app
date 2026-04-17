import json
import sqlite3
from datetime import date as dt_date, timedelta
from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db
from auth import api_admin_required, api_login_required, api_scheduler_required
from limiter import limiter

bp = Blueprint("api", __name__, url_prefix="/api")

CALL_SKILL_NAME = "Call"


# ── Auth endpoints ────────────────────────────────────────────────────────────

@bp.route("/auth/me")
def auth_me():
    if "user_id" not in session:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated":        True,
        "username":             session.get("username"),
        "role":                 session.get("role"),
        "force_password_change": session.get("force_password_change", False),
    })


@bp.route("/auth/login", methods=["POST"])
@limiter.limit("5 per minute")
def auth_login():
    data     = request.get_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    fpc = bool(user["force_password_change"])
    session["user_id"]               = user["id"]
    session["username"]              = user["username"]
    session["role"]                  = user["role"]
    session["force_password_change"] = fpc
    return jsonify({
        "ok":                    True,
        "username":              user["username"],
        "role":                  user["role"],
        "force_password_change": fpc,
    })


@bp.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/auth/change-password", methods=["POST"])
@api_login_required
def auth_change_password():
    data       = request.get_json()
    current_pw = data.get("current_password") or ""
    new_pw     = data.get("new_password") or ""

    if len(new_pw) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()

        if not user or not check_password_hash(user["password"], current_pw):
            return jsonify({"error": "Current password is incorrect"}), 401

        conn.execute(
            "UPDATE users SET password=?, force_password_change=0 WHERE id=?",
            (generate_password_hash(new_pw), session["user_id"])
        )
        conn.commit()

    session["force_password_change"] = False
    return jsonify({"ok": True})


# ── User management ───────────────────────────────────────────────────────────

@bp.route("/users")
@api_admin_required
def get_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, role, force_password_change FROM users ORDER BY username"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/users", methods=["POST"])
@api_admin_required
def create_user():
    data     = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role     = data.get("role", "staff")
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    if role not in ("admin", "scheduler", "staff"):
        return jsonify({"error": "Invalid role"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password, role, force_password_change) VALUES (?, ?, ?, 1)",
                (username, generate_password_hash(password), role)
            )
            conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Username '{username}' already exists"}), 409


@bp.route("/users/<int:user_id>", methods=["PUT"])
@api_admin_required
def update_user(user_id):
    data = request.get_json()
    role = data.get("role")
    if role not in ("admin", "scheduler", "staff"):
        return jsonify({"error": "Invalid role"}), 400
    with get_db() as conn:
        # Prevent demoting the last admin
        if role != "admin":
            target = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if target and target["role"] == "admin":
                admin_count = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin'"
                ).fetchone()[0]
                if admin_count <= 1:
                    return jsonify({"error": "Cannot demote the last admin account"}), 400
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/users/<int:user_id>", methods=["DELETE"])
@api_admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        return jsonify({"error": "Cannot delete your own account"}), 400
    with get_db() as conn:
        target = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if target and target["role"] == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin'"
            ).fetchone()[0]
            if admin_count <= 1:
                return jsonify({"error": "Cannot delete the last admin account"}), 400
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@api_admin_required
def reset_user_password(user_id):
    data   = request.get_json()
    new_pw = (data.get("password") or "").strip()
    if len(new_pw) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password=?, force_password_change=1 WHERE id=?",
            (generate_password_hash(new_pw), user_id)
        )
        conn.commit()
    return jsonify({"ok": True})


# ── Schedule events (existing calendar) ─────────────────────────────────────

@bp.route("/schedule/events")
@api_login_required
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
@api_login_required
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
@api_login_required
def get_blocks():
    with get_db() as conn:
        blocks = conn.execute(
            "SELECT * FROM schedule_blocks ORDER BY start_date DESC"
        ).fetchall()
    return jsonify([dict(b) for b in blocks])


@bp.route("/blocks", methods=["POST"])
@api_scheduler_required
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
@api_login_required
def get_block(block_id):
    with get_db() as conn:
        block = conn.execute(
            "SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)
        ).fetchone()
        if not block:
            return jsonify({"error": "not found"}), 404
    return jsonify(dict(block))


@bp.route("/blocks/<int:block_id>", methods=["DELETE"])
@api_scheduler_required
def delete_block(block_id):
    with get_db() as conn:
        conn.execute("DELETE FROM schedule_blocks WHERE id = ?", (block_id,))
        conn.commit()
    return jsonify({"ok": True})


# ── Staff & Skills ───────────────────────────────────────────────────────────

@bp.route("/staff")
@api_login_required
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
@api_admin_required
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
@api_admin_required
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
@api_admin_required
def delete_staff(staff_id):
    with get_db() as conn:
        conn.execute("DELETE FROM staff WHERE id=?", (staff_id,))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/skills")
@api_login_required
def get_skills():
    with get_db() as conn:
        skills = conn.execute("SELECT * FROM skills ORDER BY priority, name").fetchall()
    return jsonify([dict(s) for s in skills])


@bp.route("/skills", methods=["POST"])
@api_admin_required
def create_skill():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    priority = int(data.get("priority", 0))
    if not name:
        return jsonify({"error": "Name is required"}), 400
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO skills (name, priority) VALUES (?, ?)", (name, priority)
            )
            conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    except Exception:
        return jsonify({"error": f"Skill '{name}' already exists"}), 409


@bp.route("/skills/<int:skill_id>", methods=["PUT"])
@api_admin_required
def update_skill(skill_id):
    data = request.get_json()
    name = (data.get("name") or "").strip()
    priority = int(data.get("priority", 0))
    if not name:
        return jsonify({"error": "Name is required"}), 400
    with get_db() as conn:
        conn.execute(
            "UPDATE skills SET name=?, priority=? WHERE id=?", (name, priority, skill_id)
        )
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/skills/<int:skill_id>", methods=["DELETE"])
@api_admin_required
def delete_skill(skill_id):
    with get_db() as conn:
        conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        conn.commit()
    return jsonify({"ok": True})


# ── Skill minimums ────────────────────────────────────────────────────────────

@bp.route("/skill-minimums")
@api_login_required
def get_skill_minimums():
    with get_db() as conn:
        rows = conn.execute("SELECT skill_id, minimum_count FROM skill_minimums").fetchall()
    return jsonify({r["skill_id"]: r["minimum_count"] for r in rows})


@bp.route("/skill-minimums", methods=["PUT"])
@api_admin_required
def save_skill_minimums():
    data = request.get_json()  # { skill_id: minimum_count, ... }
    with get_db() as conn:
        for skill_id, minimum in data.items():
            minimum = max(0, int(minimum))
            if minimum == 0:
                conn.execute("DELETE FROM skill_minimums WHERE skill_id=?", (int(skill_id),))
            else:
                conn.execute("""
                    INSERT INTO skill_minimums (skill_id, minimum_count) VALUES (?, ?)
                    ON CONFLICT(skill_id) DO UPDATE SET minimum_count=excluded.minimum_count
                """, (int(skill_id), minimum))
        conn.commit()
    return jsonify({"ok": True})


# ── Day priorities ────────────────────────────────────────────────────────────

@bp.route("/day-priorities")
@api_login_required
def get_day_priorities():
    with get_db() as conn:
        rows = conn.execute("SELECT day_of_week, priority FROM day_priority").fetchall()
    return jsonify({r["day_of_week"]: r["priority"] for r in rows})


@bp.route("/day-priorities", methods=["PUT"])
@api_admin_required
def save_day_priorities():
    data = request.get_json()  # { "Monday": 1, "Tuesday": 3, ... }
    with get_db() as conn:
        for day, priority in data.items():
            conn.execute(
                "UPDATE day_priority SET priority=? WHERE day_of_week=?",
                (int(priority), day)
            )
        conn.commit()
    return jsonify({"ok": True})


# ── Closed dates ──────────────────────────────────────────────────────────────

@bp.route("/closed-dates")
def get_closed_dates():
    with get_db() as conn:
        rows = conn.execute("SELECT date FROM closed_dates ORDER BY date").fetchall()
    return jsonify([r["date"] for r in rows])


@bp.route("/closed-dates", methods=["POST"])
@api_admin_required
def add_closed_date():
    data = request.get_json()
    date = (data.get("date") or "").strip()
    if not date:
        return jsonify({"error": "date required"}), 400
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO closed_dates (date) VALUES (?)", (date,))
        conn.commit()
    return jsonify({"ok": True})


@bp.route("/closed-dates/<date>", methods=["DELETE"])
@api_admin_required
def delete_closed_date(date):
    with get_db() as conn:
        conn.execute("DELETE FROM closed_dates WHERE date=?", (date,))
        conn.commit()
    return jsonify({"ok": True})


# ── Template needs (slot targets) ────────────────────────────────────────────

@bp.route("/template/needs")
@api_login_required
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


@bp.route("/template/needs", methods=["PUT"])
@api_admin_required
def save_template_needs():
    """Replace all template needs. Body: [{ day, skill_id, quantity }, ...]"""
    rows = request.get_json()
    with get_db() as conn:
        conn.execute("DELETE FROM template_needs WHERE template_id=1")
        conn.execute("INSERT OR IGNORE INTO schedule_templates (id, name) VALUES (1, 'Weekly Template')")
        for row in rows:
            qty = int(row.get("quantity", 0))
            if qty <= 0:
                continue
            conn.execute("""
                INSERT INTO template_needs (template_id, day_of_week, skill_id, quantity)
                VALUES (1, ?, ?, ?)
            """, (row["day"], int(row["skill_id"]), qty))
        conn.commit()
    return jsonify({"ok": True})


# ── Block requests ───────────────────────────────────────────────────────────

@bp.route("/blocks/<int:block_id>/requests")
@api_login_required
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
@api_scheduler_required
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
@api_scheduler_required
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
@api_login_required
def get_fte_tiers():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT fte, shifts_per_week, shifts_per_pp FROM fte_tiers ORDER BY fte"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/fte-tiers", methods=["POST"])
@api_admin_required
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
@api_admin_required
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
@api_admin_required
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
@api_login_required
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
@api_login_required
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
@api_scheduler_required
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
@api_scheduler_required
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
@api_login_required
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
@api_scheduler_required
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
@api_login_required
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
@api_scheduler_required
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
@api_admin_required
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
@api_login_required
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
@api_login_required
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

