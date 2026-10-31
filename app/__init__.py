import os
from datetime import datetime

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.1.0"

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

DEFAULT_ADMIN_EMAIL = "admin@erp.co.zw"


def _database_uri():
    url = os.getenv("DATABASE_URL", "sqlite:///tylonerp.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=_database_uri(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
    )

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None

    from . import models
    from .routes import admin_bp, auth_bp, main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        return {"app_version": VERSION, "plans": models.PLANS, "now": datetime.utcnow()}

    @app.get("/healthz")
    def healthz():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "version": VERSION}

    with app.app_context():
        db.create_all()
        seed_admin(app)

    return app


def seed_admin(app):
    """Create or sync the system administrator from environment variables."""
    from .models import User

    email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL).strip().lower()
    password = os.getenv("ADMIN_PASSWORD")
    admin = User.query.filter_by(email=email).first()
    if admin is None:
        if not password:
            app.logger.warning("ADMIN_PASSWORD not set; no system administrator created")
            return
        admin = User(email=email, name="System Administrator", role="superadmin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Created system administrator %s", email)
    elif password and not admin.check_password(password):
        admin.set_password(password)
        db.session.commit()
        app.logger.info("Updated system administrator password")
