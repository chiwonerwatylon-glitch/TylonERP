import os
import re
from datetime import datetime, timedelta

from flask import Flask, g, redirect, request, url_for
from flask.sessions import SecureCookieSessionInterface
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.3.0"

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

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
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
            "pool_recycle": 1800,
        },
    )
    app.session_interface = ScopedSessionInterface()

    db.init_app(app)
    csrf.init_app(app)
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
    from .routes import admin_bp, auth_bp, main_bp
    from .workspace import public_bp, ws_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(main_bp)
    app.register_blueprint(ws_bp)
    app.register_blueprint(public_bp)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

    @app.context_processor
    def inject_globals():
        return {"app_version": VERSION, "plans": models.PLANS, "now": datetime.utcnow(),
                "theme_style": _theme_style()}

    @app.get("/healthz")
    def healthz():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "version": VERSION}

    with app.app_context():
        _bootstrap(app)

    return app


def _mix(hex_a, hex_b, t):
    a, b = (int(hex_a[i:i + 2], 16) for i in (1, 3, 5)), (int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _lum(h):
    r, g_, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g_ + 0.0722 * b


def _theme_style():
    """CSS variable overrides for the tenant whose pages are being shown."""
    from flask_login import current_user
    from .models import Tenant

    tenant = None
    if current_user.is_authenticated and not current_user.is_superadmin:
        tenant = current_user.tenant
    elif g.get("slug"):
        tenant = Tenant.query.filter_by(slug=g.slug).first()
    b = tenant.branding if tenant else None
    if not b:
        return ""
    css = []
    if b.accent:
        css += [f"--gold:{b.accent}", f"--gold2:{_mix(b.accent, '#ffffff', .35)}",
                f"--on-gold:{'#10131c' if _lum(b.accent) > .5 else '#ffffff'}"]
    if b.background:
        css += [f"--bg:{b.background}"]
    if b.panel:
        toward = "#000000" if _lum(b.panel) > .55 else "#ffffff"
        css += [f"--panel:{b.panel}", f"--panel2:{_mix(b.panel, toward, .06)}", f"--line:{_mix(b.panel, toward, .14)}"]
    if b.background or b.panel:
        light = _lum(b.panel or b.background) > .55
        if light:
            css += ["--text:#161b2e", "--muted:#5b6682"]
    return ":root{" + ";".join(css) + "}" if css else ""


def _bootstrap(app):
    """Create tables, add missing columns and seed the admin.

    Several workers start at once, so tolerate losing a race.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

    try:
        db.create_all()
    except (OperationalError, ProgrammingError, IntegrityError):
        db.session.rollback()
    _add_missing_columns()
    try:
        seed_admin(app)
    except IntegrityError:
        db.session.rollback()


def _add_missing_columns():
    """Tiny forward-only migration: add columns introduced after a table existed."""
    insp = db.inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have and col.nullable:
                ddl = col.type.compile(db.engine.dialect)
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))
                except Exception:  # another worker added it first
                    pass


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
