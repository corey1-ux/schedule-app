from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify
from flask_cors import CORS
from functools import wraps
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}}, supports_credentials=True)

DATABASE = "ir_schedule.db"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Open a new database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT    NOT NULL UNIQUE,
                password  TEXT    NOT NULL,
                role      TEXT    NOT NULL DEFAULT 'user'
            );

            CREATE TABLE IF NOT EXISTS skills (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                priority   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS staff (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                fte        REAL    NOT NULL DEFAULT 1.0,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS staff_skills (
                staff_id   INTEGER NOT NULL REFERENCES staff(id)  ON DELETE CASCADE,
                skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                PRIMARY KEY (staff_id, skill_id)
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                description TEXT,
                start_time  TEXT    NOT NULL,
                end_time    TEXT    NOT NULL,
                created_by  INTEGER REFERENCES users(id),
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS schedule_templates (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS template_needs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES schedule_templates(id) ON DELETE CASCADE,
                day_of_week TEXT    NOT NULL,
                skill_id    INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                quantity    INTEGER NOT NULL DEFAULT 1,
                UNIQUE (template_id, day_of_week, skill_id)
            );

            CREATE TABLE IF NOT EXISTS day_priority (
                day_of_week TEXT    PRIMARY KEY,
                priority    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS generated_schedule (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                result_json  TEXT,
                month_start  TEXT,
                generated_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS closed_dates (
                date TEXT PRIMARY KEY
            );
        """)

        # Migrations: add columns that may not exist on older databases
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(skills)").fetchall()]
        if "priority" not in existing_cols:
            conn.execute("ALTER TABLE skills ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")

        existing_tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "generated_schedule" not in existing_tables:
            conn.execute("""
                CREATE TABLE generated_schedule (
                    id           INTEGER PRIMARY KEY CHECK (id = 1),
                    result_json  TEXT,
                    month_start  TEXT,
                    generated_at TEXT    DEFAULT (datetime('now'))
                )
            """)
        else:
            gs_cols = [r[1] for r in conn.execute("PRAGMA table_info(generated_schedule)").fetchall()]
            if "month_start" not in gs_cols:
                conn.execute("ALTER TABLE generated_schedule ADD COLUMN month_start TEXT")

        if "closed_dates" not in existing_tables:
            conn.execute("CREATE TABLE closed_dates (date TEXT PRIMARY KEY)")

        existing = conn.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", "admin123", "admin"),
            )

        # Seed day priorities with 0 (unset) for each day if not already present
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            conn.execute(
                "INSERT OR IGNORE INTO day_priority (day_of_week, priority) VALUES (?, 0)",
                (day,)
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return login_required(decorated)


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return redirect(url_for("admin"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? AND password = ?",
                (username, password),
            ).fetchone()

        if user:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin():
    with get_db() as conn:
        users     = conn.execute("SELECT * FROM users").fetchall()
        schedules = conn.execute("""
            SELECT s.*, u.username AS creator
            FROM schedules s
            LEFT JOIN users u ON s.created_by = u.id
            ORDER BY s.start_time
        """).fetchall()
    return render_template("admin.html", users=users, schedules=schedules)


# ---------------------------------------------------------------------------
# Skills routes
# ---------------------------------------------------------------------------

@app.route("/skills")
@admin_required
def skills():
    with get_db() as conn:
        skills_list = conn.execute(
            "SELECT * FROM skills ORDER BY name"
        ).fetchall()
    return render_template("skills.html", skills=skills_list)


@app.route("/add_skill", methods=["POST"])
@admin_required
def add_skill():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Skill name is required.", "danger")
        return redirect(url_for("skills"))

    try:
        with get_db() as conn:
            conn.execute("INSERT INTO skills (name) VALUES (?)", (name,))
            conn.commit()
        flash(f"Skill '{name}' added.", "success")
    except sqlite3.IntegrityError:
        flash(f"Skill '{name}' already exists.", "warning")

    return redirect(url_for("skills"))


@app.route("/delete_skill/<int:skill_id>", methods=["POST"])
@admin_required
def delete_skill(skill_id):
    with get_db() as conn:
        skill = conn.execute(
            "SELECT name FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        if skill:
            conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
            conn.commit()
            flash(f"Skill '{skill['name']}' deleted.", "info")
        else:
            flash("Skill not found.", "danger")
    return redirect(url_for("skills"))


# ---------------------------------------------------------------------------
# Staff routes
# ---------------------------------------------------------------------------

def _staff_with_skills(conn):
    """Return all staff rows with their associated skills list."""
    staff_list = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
    result = []
    for member in staff_list:
        member_skills = conn.execute("""
            SELECT sk.id, sk.name FROM skills sk
            JOIN staff_skills ss ON sk.id = ss.skill_id
            WHERE ss.staff_id = ?
            ORDER BY sk.name
        """, (member["id"],)).fetchall()
        result.append({
            "id":         member["id"],
            "name":       member["name"],
            "fte":        member["fte"],
            "created_at": member["created_at"],
            "skills":     member_skills,
        })
    return result


@app.route("/staff")
@admin_required
def staff():
    with get_db() as conn:
        staff_list  = _staff_with_skills(conn)
        skills_list = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
    return render_template("staff.html", staff=staff_list, skills=skills_list)


@app.route("/add_staff", methods=["POST"])
@admin_required
def add_staff():
    name      = request.form.get("name", "").strip()
    fte       = request.form.get("fte", "1.0").strip()
    skill_ids = request.form.getlist("skill_ids")

    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("staff"))

    try:
        fte = float(fte)
        if not (0.0 < fte <= 1.0):
            raise ValueError
    except ValueError:
        flash("FTE must be a number between 0 and 1.", "danger")
        return redirect(url_for("staff"))

    with get_db() as conn:
        cursor   = conn.execute("INSERT INTO staff (name, fte) VALUES (?, ?)", (name, fte))
        staff_id = cursor.lastrowid
        for sid in skill_ids:
            conn.execute(
                "INSERT OR IGNORE INTO staff_skills (staff_id, skill_id) VALUES (?, ?)",
                (staff_id, int(sid)),
            )
        conn.commit()

    flash(f"Staff member '{name}' added.", "success")
    return redirect(url_for("staff"))


@app.route("/delete_staff/<int:staff_id>", methods=["POST"])
@admin_required
def delete_staff(staff_id):
    with get_db() as conn:
        member = conn.execute(
            "SELECT name FROM staff WHERE id = ?", (staff_id,)
        ).fetchone()
        if member:
            conn.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
            conn.commit()
            flash(f"'{member['name']}' removed.", "info")
        else:
            flash("Staff member not found.", "danger")
    return redirect(url_for("staff"))




# ---------------------------------------------------------------------------
# Schedule Template routes  (single repeating weekly template)
# ---------------------------------------------------------------------------

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_or_create_weekly_template(conn):
    """Return the single weekly template row, creating it if it doesn't exist."""
    t = conn.execute("SELECT * FROM schedule_templates WHERE id = 1").fetchone()
    if not t:
        conn.execute("INSERT INTO schedule_templates (id, name) VALUES (1, 'Weekly Template')")
        conn.commit()
        t = conn.execute("SELECT * FROM schedule_templates WHERE id = 1").fetchone()
    return t


def _get_needs(conn):
    """Return needs dict: needs[day][skill_id] = quantity."""
    rows = conn.execute("""
        SELECT tn.*, sk.name AS skill_name
        FROM template_needs tn
        JOIN skills sk ON sk.id = tn.skill_id
        WHERE tn.template_id = 1
    """).fetchall()
    needs = {day: {} for day in DAYS}
    for row in rows:
        needs[row["day_of_week"]][row["skill_id"]] = row["quantity"]
    return needs


def _get_day_priorities(conn):
    """Return dict: day_of_week -> priority."""
    rows = conn.execute("SELECT * FROM day_priority").fetchall()
    return {row["day_of_week"]: row["priority"] for row in rows}


@app.route("/schedule_template")
@admin_required
def schedule_template():
    with get_db() as conn:
        _get_or_create_weekly_template(conn)
        skills_list    = conn.execute("""
            SELECT * FROM skills
            ORDER BY CASE WHEN priority = 0 THEN 999 ELSE priority END, name
        """).fetchall()
        needs          = _get_needs(conn)
        day_priorities = _get_day_priorities(conn)
    days_sorted = sorted(DAYS, key=lambda d: (day_priorities.get(d, 0) or 999, DAYS.index(d)))
    return render_template("schedule_template.html",
                           skills=skills_list, days=DAYS,
                           days_sorted=days_sorted,
                           needs=needs, day_priorities=day_priorities)


@app.route("/schedule_template/save_priorities", methods=["POST"])
@admin_required
def save_priorities():
    """Save skill fill priorities."""
    with get_db() as conn:
        for key, value in request.form.items():
            if not key.startswith("priority__"):
                continue
            try:
                _, skill_id = key.split("__")
                priority = max(0, int(value))
            except (ValueError, TypeError):
                continue
            conn.execute(
                "UPDATE skills SET priority = ? WHERE id = ?",
                (priority, int(skill_id))
            )
        conn.commit()
    flash("Skill priorities saved.", "success")
    return redirect(url_for("schedule_template"))


@app.route("/schedule_template/save_day_priorities", methods=["POST"])
@admin_required
def save_day_priorities():
    """Save day-of-week fill priorities."""
    with get_db() as conn:
        for day in DAYS:
            value = request.form.get(f"day_priority__{day}", "0")
            try:
                priority = max(0, int(value))
            except (ValueError, TypeError):
                priority = 0
            conn.execute(
                "UPDATE day_priority SET priority = ? WHERE day_of_week = ?",
                (priority, day)
            )
        conn.commit()
    flash("Day priorities saved.", "success")
    return redirect(url_for("schedule_template"))


@app.route("/schedule_template/save", methods=["POST"])
@admin_required
def save_needs():
    """Bulk-save all day/skill quantities from the grid form."""
    with get_db() as conn:
        _get_or_create_weekly_template(conn)
        # Wipe existing needs and replace with submitted values
        conn.execute("DELETE FROM template_needs WHERE template_id = 1")
        for key, value in request.form.items():
            # fields are named need__{day}__{skill_id}
            if not key.startswith("need__"):
                continue
            try:
                _, day, skill_id = key.split("__")
                quantity = int(value)
            except (ValueError, TypeError):
                continue
            if day not in DAYS or quantity < 0:
                continue
            if quantity > 0:
                conn.execute("""
                    INSERT INTO template_needs (template_id, day_of_week, skill_id, quantity)
                    VALUES (1, ?, ?, ?)
                """, (day, int(skill_id), quantity))
        conn.commit()
    flash("Schedule template saved.", "success")
    return redirect(url_for("schedule_template"))


@app.route("/schedule_template/clear", methods=["POST"])
@admin_required
def clear_needs():
    """Delete all needs from the weekly template."""
    with get_db() as conn:
        conn.execute("DELETE FROM template_needs WHERE template_id = 1")
        conn.commit()
    flash("All needs cleared.", "info")
    return redirect(url_for("schedule_template"))

# ---------------------------------------------------------------------------
# Closed dates routes
# ---------------------------------------------------------------------------

@app.route("/closed_dates")
@admin_required
def closed_dates():
    with get_db() as conn:
        dates = [r["date"] for r in conn.execute(
            "SELECT date FROM closed_dates ORDER BY date"
        ).fetchall()]
    return render_template("closed_dates.html", closed_dates=dates)


@app.route("/closed_dates/add", methods=["POST"])
@admin_required
def add_closed_date():
    date = request.form.get("date", "").strip()
    if not date:
        flash("Date is required.", "danger")
        return redirect(url_for("closed_dates"))
    try:
        from datetime import date as dt_date
        dt_date.fromisoformat(date)  # validate format
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO closed_dates (date) VALUES (?)", (date,))
            conn.commit()
        flash(f"{date} marked as closed.", "success")
    except ValueError:
        flash("Invalid date format.", "danger")
    return redirect(url_for("closed_dates"))


@app.route("/closed_dates/delete/<date>", methods=["POST"])
@admin_required
def delete_closed_date(date):
    with get_db() as conn:
        conn.execute("DELETE FROM closed_dates WHERE date = ?", (date,))
        conn.commit()
    flash(f"{date} removed.", "info")
    return redirect(url_for("closed_dates"))


# ---------------------------------------------------------------------------
# Schedule routes
# ---------------------------------------------------------------------------

import json
import calendar as cal_mod
from datetime import date as dt_date, timedelta
from schedule_generator import generate_month as generate_schedule


@app.route("/schedule")
@admin_required
def schedule():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM generated_schedule WHERE id = 1").fetchone()
    if row and row["result_json"]:
        result       = json.loads(row["result_json"])
        generated_at = row["generated_at"]
        month_start  = row["month_start"]
        unmet        = result.pop("unmet", {})
    else:
        result       = None
        generated_at = None
        month_start  = None
        unmet        = {}

    today = dt_date.today()
    default_month = today.strftime("%Y-%m")

    return render_template("schedule.html",
                           has_schedule=(result is not None),
                           unmet=unmet,
                           generated_at=generated_at,
                           month_start=month_start,
                           default_month=default_month)


@app.route("/schedule/generate", methods=["POST"])
@admin_required
def run_generate_schedule():
    month_str = request.form.get("month", "").strip()  # e.g. "2025-07"
    if not month_str:
        flash("Please select a month.", "danger")
        return redirect(url_for("schedule"))

    try:
        year, month = [int(x) for x in month_str.split("-")]
        month_start = dt_date(year, month, 1)
    except (ValueError, TypeError):
        flash("Invalid month.", "danger")
        return redirect(url_for("schedule"))

    with get_db() as conn:
        closed = set(r["date"] for r in conn.execute(
            "SELECT date FROM closed_dates"
        ).fetchall())
        result = generate_schedule(conn, month_start, closed)
        conn.execute("""
            INSERT INTO generated_schedule (id, result_json, month_start, generated_at)
            VALUES (1, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                result_json  = excluded.result_json,
                month_start  = excluded.month_start,
                generated_at = excluded.generated_at
        """, (json.dumps(result), month_start.isoformat()))
        conn.commit()

    flash(f"Schedule generated for {month_start.strftime('%B %Y')}.", "success")
    return redirect(url_for("schedule"))


@app.route("/schedule/events")
@admin_required
def schedule_events():
    """Return schedule as JSON events for React Big Calendar."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM generated_schedule WHERE id = 1").fetchone()

    if not row or not row["result_json"]:
        return json.dumps([]), 200, {"Content-Type": "application/json"}

    result = json.loads(row["result_json"])
    result.pop("unmet", None)

    events = []
    # result is keyed by ISO date string: { "2025-07-01": { skill: [names] } }
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

    return json.dumps(events), 200, {"Content-Type": "application/json"}


@app.route("/schedule/debug")
@admin_required
def schedule_debug():
    """Plain-text debug view of the stored schedule data."""
    with get_db() as conn:
        row = conn.execute("SELECT id, month_start, generated_at, length(result_json) as json_len FROM generated_schedule WHERE id = 1").fetchone()
        if not row:
            return "No schedule in database.", 200
        result = json.loads(conn.execute("SELECT result_json FROM generated_schedule WHERE id = 1").fetchone()["result_json"])

    unmet  = result.pop("unmet", {})
    lines  = [f"month_start: {row['month_start']}", f"generated_at: {row['generated_at']}", f"json_size: {row['json_len']} bytes", f"date_keys: {len(result)}", ""]
    for date_str in sorted(result.keys())[:10]:  # show first 10 days
        lines.append(f"{date_str}: {result[date_str]}")
    if len(result) > 10:
        lines.append(f"... and {len(result)-10} more days")
    lines.append(f"\nunmet: {unmet}")
    return "<pre>" + "\n".join(lines) + "</pre>", 200


# ---------------------------------------------------------------------------
# JSON API routes (consumed by React frontend at localhost:3000)
# ---------------------------------------------------------------------------

@app.route("/api/schedule/events")
def api_schedule_events():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM generated_schedule WHERE id = 1"
        ).fetchone()

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


@app.route("/api/schedule/meta")
def api_schedule_meta():
    with get_db() as conn:
        row = conn.execute(
            "SELECT month_start, generated_at FROM generated_schedule WHERE id = 1"
        ).fetchone()

    if not row:
        return jsonify({"month_start": None, "generated_at": None})

    return jsonify({
        "month_start":  row["month_start"],
        "generated_at": row["generated_at"],
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)