import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, send_from_directory
from flask_cors import CORS
from database import init_db, init_blocks_db
from limiter import limiter
import auth
import admin
import skills
import staff
import schedule_template
import schedule
import api
import import_schedule


def create_app():
    build_dir = os.path.join(os.path.dirname(__file__), 'frontend', 'build')

    app = Flask(__name__, static_folder=build_dir, static_url_path='')

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Add a long random string to your .env file."
        )
    app.secret_key = secret_key

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("FLASK_ENV") == "production":
        app.config["SESSION_COOKIE_SECURE"] = True

    cors_origin = os.environ.get("CORS_ORIGIN", "http://localhost:3000")
    if cors_origin:
        CORS(app,
             resources={r"/api/*": {"origins": cors_origin}},
             supports_credentials=True)

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(skills.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(schedule_template.bp)
    app.register_blueprint(schedule.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(import_schedule.bp)

    limiter.init_app(app)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_react(path):
        full_path = os.path.join(build_dir, path)
        if path and os.path.exists(full_path):
            return send_from_directory(build_dir, path)
        return send_from_directory(build_dir, 'index.html')

    init_db()
    init_blocks_db()

    return app
