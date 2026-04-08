from flask import Blueprint, render_template, redirect, url_for
from database import get_db
from auth import admin_required

bp = Blueprint("admin", __name__)


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("admin.dashboard"))


@bp.route("/admin")
@admin_required
def dashboard():
    with get_db() as conn:
        users     = conn.execute("SELECT * FROM users").fetchall()
        schedules = conn.execute("""
            SELECT s.*, u.username AS creator
            FROM schedules s
            LEFT JOIN users u ON s.created_by = u.id
            ORDER BY s.start_time
        """).fetchall()
    return render_template("admin.html", users=users, schedules=schedules)