import json
from flask import Blueprint, jsonify
from database import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


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

    return jsonify({
        "month_start":  row["month_start"],
        "generated_at": row["generated_at"],
    })