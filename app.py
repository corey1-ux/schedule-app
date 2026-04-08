import os
from flask import Flask
from flask_cors import CORS
from database import init_db
import auth
import admin
import skills
import staff
import schedule_template
import schedule
import api


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}}, supports_credentials=True)

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(skills.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(schedule_template.bp)
    app.register_blueprint(schedule.bp)
    app.register_blueprint(api.bp)

    return app