import json
from datetime import date as dt_date
from flask import Blueprint, render_template, redirect, url_for, request, flash
from database import get_db
from auth import admin_required
from schedule_generator import generate_month

bp = Blueprint("schedule", __name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@bp.route("/closed_dates")
@admin_required
def closed_dates():
    with get_db() as conn:
        dates = [r["date"] for r in conn.execute(
            "SELECT date FROM closed_dates ORDER BY date"
        ).fetchall()]
    return render_template("closed_dates.html", closed_dates=dates)


@bp.route("/closed_dates/add", methods=["POST"])
@admin_required
def add_closed_date():
    date = request.form.get("date", "").strip()
    if not date:
        flash("Date is required.", "danger")
        return redirect(url_for("schedule.closed_dates"))
    try:
        dt_date.fromisoformat(date)
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO closed_dates (date) VALUES (?)", (date,))
            conn.commit()
        flash(f"{date} marked as closed.", "success")
    except ValueError:
        flash("Invalid date format.", "danger")
    return redirect(url_for("schedule.closed_dates"))


@bp.route("/closed_dates/delete/<date>", methods=["POST"])
@admin_required
def delete_closed_date(date):
    with get_db() as conn:
        conn.execute("DELETE FROM closed_dates WHERE date = ?", (date,))
        conn.commit()
    flash(f"{date} removed.", "info")
    return redirect(url_for("schedule.closed_dates"))


@bp.route("/schedule")
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

    default_month = dt_date.today().strftime("%Y-%m")

    return render_template("schedule.html",
                           has_schedule=(result is not None),
                           unmet=unmet,
                           generated_at=generated_at,
                           month_start=month_start,
                           default_month=default_month)


@bp.route("/schedule/generate", methods=["POST"])
@admin_required
def run_generate_schedule():
    month_str = request.form.get("month", "").strip()
    if not month_str:
        flash("Please select a month.", "danger")
        return redirect(url_for("schedule.schedule"))

    try:
        year, month = [int(x) for x in month_str.split("-")]
        month_start = dt_date(year, month, 1)
    except (ValueError, TypeError):
        flash("Invalid month.", "danger")
        return redirect(url_for("schedule.schedule"))

    with get_db() as conn:
        closed = set(r["date"] for r in conn.execute("SELECT date FROM closed_dates").fetchall())
        result = generate_month(conn, month_start, closed)
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
    return redirect(url_for("schedule.schedule"))


@bp.route("/schedule/debug")
@admin_required
def schedule_debug():
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, month_start, generated_at, length(result_json) as json_len "
            "FROM generated_schedule WHERE id = 1"
        ).fetchone()
        if not row:
            return "No schedule in database.", 200
        result = json.loads(conn.execute(
            "SELECT result_json FROM generated_schedule WHERE id = 1"
        ).fetchone()["result_json"])

    unmet = result.pop("unmet", {})
    lines = [
        f"month_start: {row['month_start']}",
        f"generated_at: {row['generated_at']}",
        f"json_size: {row['json_len']} bytes",
        f"date_keys: {len(result)}", ""
    ]
    for date_str in sorted(result.keys())[:10]:
        lines.append(f"{date_str}: {result[date_str]}")
    if len(result) > 10:
        lines.append(f"... and {len(result) - 10} more days")
    lines.append(f"\nunmet: {unmet}")
    return "<pre>" + "\n".join(lines) + "</pre>", 200