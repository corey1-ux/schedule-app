import sqlite3
from flask import Blueprint, render_template, redirect, url_for, request, flash
from database import get_db
from auth import admin_required

bp = Blueprint("skills", __name__)


@bp.route("/skills")
@admin_required
def skills():
    with get_db() as conn:
        skills_list = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
    return render_template("skills.html", skills=skills_list)


@bp.route("/add_skill", methods=["POST"])
@admin_required
def add_skill():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Skill name is required.", "danger")
        return redirect(url_for("skills.skills"))
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO skills (name) VALUES (?)", (name,))
            conn.commit()
        flash(f"Skill '{name}' added.", "success")
    except sqlite3.IntegrityError:
        flash(f"Skill '{name}' already exists.", "warning")
    return redirect(url_for("skills.skills"))


@bp.route("/delete_skill/<int:skill_id>", methods=["POST"])
@admin_required
def delete_skill(skill_id):
    with get_db() as conn:
        skill = conn.execute("SELECT name FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if skill:
            conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
            conn.commit()
            flash(f"Skill '{skill['name']}' deleted.", "info")
        else:
            flash("Skill not found.", "danger")
    return redirect(url_for("skills.skills"))