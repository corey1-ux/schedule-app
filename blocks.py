import json
from datetime import date as dt_date, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash
from database import get_db
from auth import admin_required

bp = Blueprint("blocks", __name__)


def _block_dates(start_date, end_date):
    """Return all dates in a block as ISO strings."""
    dates = []
    d = dt_date.fromisoformat(start_date)
    end = dt_date.fromisoformat(end_date)
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


@bp.route("/blocks")
@admin_required
def blocks():
    with get_db() as conn:
        blocks_list = conn.execute(
            "SELECT * FROM schedule_blocks ORDER BY start_date DESC"
        ).fetchall()
    return render_template("blocks.html", blocks=blocks_list)


@bp.route("/blocks/create", methods=["POST"])
@admin_required
def create_block():
    name       = request.form.get("name", "").strip()
    start_date = request.form.get("start_date", "").strip()

    if not name or not start_date:
        flash("Name and start date are required.", "danger")
        return redirect(url_for("blocks.blocks"))

    try:
        start = dt_date.fromisoformat(start_date)
        end   = start + timedelta(weeks=8) - timedelta(days=1)
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("blocks.blocks"))

    with get_db() as conn:
        conn.execute(
            "INSERT INTO schedule_blocks (name, start_date, end_date) VALUES (?, ?, ?)",
            (name, start.isoformat(), end.isoformat())
        )
        conn.commit()

    flash(f"Block '{name}' created.", "success")
    return redirect(url_for("blocks.blocks"))


@bp.route("/blocks/<int:block_id>/delete", methods=["POST"])
@admin_required
def delete_block(block_id):
    with get_db() as conn:
        conn.execute("DELETE FROM schedule_blocks WHERE id = ?", (block_id,))
        conn.commit()
    flash("Block deleted.", "info")
    return redirect(url_for("blocks.blocks"))


@bp.route("/blocks/<int:block_id>/publish", methods=["POST"])
@admin_required
def publish_block(block_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE schedule_blocks SET status = 'published' WHERE id = ?", (block_id,)
        )
        conn.commit()
    flash("Block published.", "success")
    return redirect(url_for("blocks.blocks"))