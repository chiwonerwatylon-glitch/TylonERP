import logging
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, g, redirect, request, url_for
from flask.sessions import SecureCookieSessionInterface
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import load_settings
from .security import init_security, limiter
from .services.theme import accent_css, auth_palette

VERSION = "1.6.1"

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")

DEFAULT_ADMIN_EMAIL = "admin@erp.co.zw"


TENANT_PATH = re.compile(r"^/t/([a-z0-9][a-z0-9-]*)(?:/|$)")


def _slug_from_path():
    m = TENANT_PATH.match(request.path)
    return m.group(1) if m else None


class ScopedSessionInterface(SecureCookieSessionInterface):
    """One signed-cookie session per sign-in area.

    The system administrator and every tenant get their own cookie, so being
    signed in as one never signs you out of another in the same browser.
    Sessions are stateless (nothing stored server side), so any replica can
    serve any user.
    """

    def get_cookie_name(self, app):
        slug = _slug_from_path()
        return f"tsess_{slug}" if slug else "tsess_admin"

    def get_cookie_path(self, app):
        slug = _slug_from_path()
        return f"/t/{slug}" if slug else "/"


def create_app(config=None):
    """Build the app. `config` is an optional dict of Flask config overrides (used by tests)."""
    settings = load_settings()
    for warning in settings.validate_for_runtime():
        logging.getLogger(__name__).warning(warning)

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.extensions["settings"] = settings
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        PERMANENT_SESSION_LIFETIME=settings.session_lifetime,
        LOGIN_RATE_LIMIT=settings.login_rate_limit,
        RATELIMIT_ENABLED=settings.ratelimit_enabled,
        RATELIMIT_STORAGE_URI=settings.ratelimit_storage_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_recycle": 1800,
        },
    )
    if config:
        app.config.update(config)
    app.session_interface = ScopedSessionInterface()

    db.init_app(app)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    csrf.init_app(app)
    limiter.init_app(app)
    init_security(app)
    login_manager.init_app(app)
    login_manager.login_message = None

    @login_manager.unauthorized_handler
    def unauthorized():
        slug = _slug_from_path()
        return redirect(url_for("auth.login", slug=slug, next=request.full_path.rstrip("?") if request.method == "GET" else None))

    @app.url_defaults
    def fill_slug(endpoint, values):
        slug = g.get("slug")
        if slug and "slug" not in values and app.url_map.is_endpoint_expecting(endpoint, "slug"):
            values["slug"] = slug

    @app.before_request
    def remember_slug():
        g.slug = _slug_from_path()

    from . import models
    from .cli import init_cli
    from .routes import admin_bp, auth_bp, main_bp
    from .workspace import public_bp, ws_bp

    init_cli(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(main_bp)
    app.register_blueprint(ws_bp)
    app.register_blueprint(public_bp)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

    @app.context_processor
    def inject_globals():
        return {"app_version": VERSION, "plans": models.PLANS, "now": datetime.utcnow(),
                "theme_style": _theme_style(), "auth_colors": _auth_colors()}

    @app.get("/healthz")
    def healthz():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "version": VERSION}

    with app.app_context():
        _bootstrap(app)

    return app


def _tenant_for_theme():
    from flask_login import current_user

    from .models import Tenant

    if current_user.is_authenticated and not current_user.is_superadmin:
        return current_user.tenant
    if g.get("slug"):
        return Tenant.query.filter_by(slug=g.slug).first()
    return None


def _theme_style():
    """The tenant's accent colour, applied on top of Bootstrap's theme in both light and dark mode."""
    tenant = _tenant_for_theme()
    b = tenant.branding if tenant else None
    return accent_css(b.accent) if b else ""


def _auth_colors():
    """The tenant's own background and panel colours; they style the sign-in page only."""
    tenant = _tenant_for_theme()
    b = tenant.branding if tenant else None
    return auth_palette(b.background, b.panel) if b else None


def run_migrations(app):
    """Bring the database to the latest schema (alembic upgrade head)."""
    from flask_migrate import upgrade
    from sqlalchemy.exc import OperationalError, ProgrammingError

    try:
        upgrade(directory=MIGRATIONS_DIR)
    except (OperationalError, ProgrammingError):
        # Several workers can start together on SQLite; the one that loses the race finds the work done
        db.session.rollback()
        app.logger.warning("Migration raced with another worker; continuing", exc_info=True)


def _bootstrap(app):
    """Apply migrations when this process owns the schema, then seed the administrator."""
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

    if app.extensions["settings"].should_auto_migrate:
        run_migrations(app)
    try:
        seed_admin(app)
    except IntegrityError:
        db.session.rollback()
    except (OperationalError, ProgrammingError):
        # Tables do not exist yet: the pre-deploy step (flask db upgrade) has not run
        db.session.rollback()
        app.logger.warning("Database schema is missing; run `flask db upgrade`")


def seed_admin(app):
    """Create or sync the system administrator from environment variables."""
    from .models import User

    settings = app.extensions["settings"]
    email = (settings.admin_email or DEFAULT_ADMIN_EMAIL).strip().lower()
    password = settings.admin_password
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
