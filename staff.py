from flask import Blueprint, render_template, redirect, url_for, request, flash
from database import get_db
from auth import admin_required

bp = Blueprint("staff", __name__)


def _staff_with_skills(conn):
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


@bp.route("/staff")
@admin_required
def staff():
    with get_db() as conn:
        staff_list  = _staff_with_skills(conn)
        skills_list = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
    return render_template("staff.html", staff=staff_list, skills=skills_list)


@bp.route("/add_staff", methods=["POST"])
@admin_required
def add_staff():
    name      = request.form.get("name", "").strip()
    fte       = request.form.get("fte", "1.0").strip()
    skill_ids = request.form.getlist("skill_ids")

    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("staff.staff"))

    try:
        fte = float(fte)
        if not (0.0 < fte <= 1.0):
            raise ValueError
    except ValueError:
        flash("FTE must be a number between 0 and 1.", "danger")
        return redirect(url_for("staff.staff"))

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
    return redirect(url_for("staff.staff"))


@bp.route("/delete_staff/<int:staff_id>", methods=["POST"])
@admin_required
def delete_staff(staff_id):
    with get_db() as conn:
        member = conn.execute("SELECT name FROM staff WHERE id = ?", (staff_id,)).fetchone()
        if member:
            conn.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
            conn.commit()
            flash(f"'{member['name']}' removed.", "info")
        else:
            flash("Staff member not found.", "danger")
    return redirect(url_for("staff.staff"))