from flask import Blueprint, render_template, redirect, url_for, request, flash
from database import get_db
from auth import admin_required

bp = Blueprint("schedule_template", __name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_or_create_weekly_template(conn):
    t = conn.execute("SELECT * FROM schedule_templates WHERE id = 1").fetchone()
    if not t:
        conn.execute("INSERT INTO schedule_templates (id, name) VALUES (1, 'Weekly Template')")
        conn.commit()
        t = conn.execute("SELECT * FROM schedule_templates WHERE id = 1").fetchone()
    return t


def _get_needs(conn):
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
    rows = conn.execute("SELECT * FROM day_priority").fetchall()
    return {row["day_of_week"]: row["priority"] for row in rows}


@bp.route("/schedule_template")
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
    days_sorted = sorted(
        DAYS, key=lambda d: (day_priorities.get(d, 0) or 999, DAYS.index(d))
    )
    return render_template("schedule_template.html",
                           skills=skills_list, days=DAYS,
                           days_sorted=days_sorted,
                           needs=needs, day_priorities=day_priorities)


@bp.route("/schedule_template/save_priorities", methods=["POST"])
@admin_required
def save_priorities():
    with get_db() as conn:
        for key, value in request.form.items():
            if not key.startswith("priority__"):
                continue
            try:
                _, skill_id = key.split("__")
                priority = max(0, int(value))
            except (ValueError, TypeError):
                continue
            conn.execute("UPDATE skills SET priority = ? WHERE id = ?", (priority, int(skill_id)))
        conn.commit()
    flash("Skill priorities saved.", "success")
    return redirect(url_for("schedule_template.schedule_template"))


@bp.route("/schedule_template/save_day_priorities", methods=["POST"])
@admin_required
def save_day_priorities():
    with get_db() as conn:
        for day in DAYS:
            value = request.form.get(f"day_priority__{day}", "0")
            try:
                priority = max(0, int(value))
            except (ValueError, TypeError):
                priority = 0
            conn.execute(
                "UPDATE day_priority SET priority = ? WHERE day_of_week = ?", (priority, day)
            )
        conn.commit()
    flash("Day priorities saved.", "success")
    return redirect(url_for("schedule_template.schedule_template"))


@bp.route("/schedule_template/save", methods=["POST"])
@admin_required
def save_needs():
    with get_db() as conn:
        _get_or_create_weekly_template(conn)
        conn.execute("DELETE FROM template_needs WHERE template_id = 1")
        for key, value in request.form.items():
            if not key.startswith("need__"):
                continue
            try:
                _, day, skill_id = key.split("__")
                quantity = int(value)
            except (ValueError, TypeError):
                continue
            if day not in DAYS or quantity <= 0:
                continue
            conn.execute("""
                INSERT INTO template_needs (template_id, day_of_week, skill_id, quantity)
                VALUES (1, ?, ?, ?)
            """, (day, int(skill_id), quantity))
        conn.commit()
    flash("Schedule template saved.", "success")
    return redirect(url_for("schedule_template.schedule_template"))


@bp.route("/schedule_template/clear", methods=["POST"])
@admin_required
def clear_needs():
    with get_db() as conn:
        conn.execute("DELETE FROM template_needs WHERE template_id = 1")
        conn.commit()
    flash("All needs cleared.", "info")
    return redirect(url_for("schedule_template.schedule_template"))