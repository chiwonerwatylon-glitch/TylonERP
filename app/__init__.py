import logging
import re

from flask import Flask, g, redirect, request, url_for
from flask.sessions import SecureCookieSessionInterface
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import load_settings
from .security import init_security, limiter

VERSION = "1.10.0"

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
    from .api import api_bp, mobile_bp
    from .routes import admin_bp, auth_bp, main_bp
    from .workspace import public_bp, ws_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(main_bp)
    app.register_blueprint(ws_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(mobile_bp)
    csrf.exempt(api_bp)  # the phone authenticates with a bearer token, not a browser session
    csrf.exempt(mobile_bp)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

    @app.context_processor
    def inject_globals():
        return {"app_version": VERSION, "plans": models.PLANS, "now": models.utcnow(),
                "theme_style": _theme_style(), "auth_colors": _auth_colors()}

    _register_error_pages(app)

    @app.get("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"), 301)

    @app.get("/healthz")
    def healthz():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "version": VERSION}

    with app.app_context():
        _bootstrap(app)

    return app


ERROR_PAGES = {
    400: ("That request did not make sense", "Something in the form or link was not right. Go back and try again."),
    403: ("You do not have access to this page", "Ask an admin in your business if you think you should."),
    404: ("This page does not exist", "The link may be old, or the item was removed."),
    413: ("That file is too big", "Pictures must be 2 MB or smaller, and import files 1 MB or smaller."),
    429: ("Too many attempts", "Wait a minute, then try again."),
    500: ("Something went wrong on our side", "Your last action may not have been saved. Try again in a moment."),
}


def _register_error_pages(app):
    from flask import render_template

    def page(code):
        title, message = ERROR_PAGES[code]
        if code == 500:
            db.session.rollback()
        try:
            return render_template("error.html", code=code, title=title, message=message), code
        except Exception:  # never let the error page itself fail
            return f"{code} {title}", code

    for code in ERROR_PAGES:
        app.register_error_handler(code, lambda e, code=code: page(code))


def _mix(hex_a, hex_b, t):
    a, b = (int(hex_a[i:i + 2], 16) for i in (1, 3, 5)), (int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _lum(h):
    r, g_, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g_ + 0.0722 * b


def _tenant_for_theme():
    from flask_login import current_user

    from .models import Tenant

    if current_user.is_authenticated and not current_user.is_superadmin:
        return current_user.tenant
    if g.get("slug"):
        return Tenant.query.filter_by(slug=g.slug).first()
    return None


def _rgb(h):
    return ",".join(str(int(h[i:i + 2], 16)) for i in (1, 3, 5))


def _toward(h, target, cond):
    """Mix colour `h` toward `target` in small steps until `cond(colour)` holds."""
    for i in range(0, 21):
        c = _mix(h, target, i / 20)
        if cond(c):
            return c
    return target


def _lift(h, target):
    """Raise a colour's lightness (keeping its hue and most of its saturation) until it reaches `target` brightness."""
    import colorsys

    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    for step in range(0, 41):
        ll = light + (0.92 - light) * step / 40
        rgb = colorsys.hls_to_rgb(hue, ll, min(1.0, sat * 1.1))
        c = "#%02x%02x%02x" % tuple(round(x * 255) for x in rgb)
        if _lum(c) >= target:
            return c
    return c


def accent_palette(a):
    """Everything the theme needs from one tenant accent, readable in light and dark mode.

    Any colour a tenant picks works: a very light accent gets dark button text and darker links; a very dark accent
    is lifted in dark mode so it still stands out; panels that carry white text always get a dark enough shade.
    """
    on = lambda c: "#0b1410" if _lum(c) > .55 else "#ffffff"  # noqa: E731
    link_light = _toward(a, "#000000", lambda c: _lum(c) <= .32)
    hero = _toward(a, "#000000", lambda c: _lum(c) <= .3)
    dark = a if _lum(a) >= .55 else _lift(a, .55)
    return {
        "light": {"primary": a, "on": on(a), "link": link_light, "hover": _mix(link_light, "#000000", .2),
                  "hero_a": hero, "hero_b": _mix(hero, "#000000", .55)},
        "dark": {"primary": dark, "on": on(dark), "link": dark, "hover": _mix(dark, "#ffffff", .25),
                 "hero_a": _mix(hero, "#0b100e", .25), "hero_b": _mix(hero, "#0b100e", .82)},
    }


def _theme_style():
    """The tenant's accent colour, applied on top of the theme in both light and dark mode."""
    tenant = _tenant_for_theme()
    b = tenant.branding if tenant else None
    if not b or not b.accent:
        return ""
    pal = accent_palette(b.accent)
    css = []
    for sel, v in ((":root,[data-bs-theme=light]", pal["light"]), ("[data-bs-theme=dark]", pal["dark"])):
        css.append(
            "%s{--bs-primary:%s;--bs-primary-rgb:%s;--on-primary:%s;--bs-link-color:%s;--bs-link-color-rgb:%s;"
            "--bs-link-hover-color:%s;--bs-link-hover-color-rgb:%s;--hero-a:%s;--hero-b:%s}"
            % (sel, v["primary"], _rgb(v["primary"]), v["on"], v["link"], _rgb(v["link"]), v["hover"], _rgb(v["hover"]),
               v["hero_a"], v["hero_b"]))
    return "".join(css)


def _auth_colors():
    """The tenant's own background and panel colours; they style the sign-in page only."""
    tenant = _tenant_for_theme()
    b = tenant.branding if tenant else None
    if not b or not (b.background or b.panel):
        return None
    panel = b.panel or b.background
    bg = b.background or b.panel
    light = _lum(panel) > .55
    return {"bg": bg, "panel": panel, "mode": "light" if light else "dark",
            "text": "#161b2e" if light else "#e8ecf6", "muted": "#5b6682" if light else "#8d99b8",
            "line": _mix(panel, "#000000" if light else "#ffffff", .16),
            "hero_text": "#161b2e" if _lum(bg) > .55 else "#ffffff", "hero_b": _mix(bg, "#000000", .3)}


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
        with db.engine.begin() as conn:
            conn.execute(db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_barcode ON products (tenant_id, barcode)"))
    except Exception:
        pass
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
