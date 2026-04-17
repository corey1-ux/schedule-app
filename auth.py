from functools import wraps
from flask import Blueprint, session, jsonify

bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return login_required(decorated)


def api_login_required(f):
    """Any authenticated user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def api_scheduler_required(f):
    """Admin or scheduler role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") not in ("admin", "scheduler"):
            return jsonify({"error": "Access denied"}), 403
        return f(*args, **kwargs)
    return api_login_required(decorated)


def api_admin_required(f):
    """Admin role only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return api_login_required(decorated)
