import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, login_required, login_user, logout_user

from . import VERSION, db
from .models import PLAN_ORDER, PLANS, Tenant, User

auth_bp = Blueprint("auth", __name__)
admin_bp = Blueprint("admin", __name__)
main_bp = Blueprint("main", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58}[a-z0-9])$")
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15


def superadmin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_superadmin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


def _home_for(user):
    if user.is_superadmin:
        return url_for("admin.dashboard")
    return url_for("ws.home", slug=user.tenant.slug)


# ---------------------------------------------------------------- auth

@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/t/<slug>", methods=["GET", "POST"])
def login(slug=None):
    tenant = Tenant.query.filter_by(slug=slug).first_or_404() if slug else None
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.is_locked():
            flash("Too many failed attempts. Try again in a few minutes.", "error")
        elif user and user.check_password(password) and tenant and user.tenant_id != tenant.id:
            flash("Incorrect email or password.", "error")
        elif user and user.check_password(password):
            if not user.is_active:
                flash("This account is disabled. Contact your administrator.", "error")
            else:
                user.failed_attempts = 0
                user.locked_until = None
                user.last_login = datetime.utcnow()
                db.session.commit()
                login_user(user)
                session.permanent = bool(request.form.get("remember"))
                return redirect(_safe_next(request.args.get("next")) or _home_for(user))
        else:
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= MAX_ATTEMPTS:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=LOCK_MINUTES)
                    user.failed_attempts = 0
                db.session.commit()
            flash("Incorrect email or password.", "error")
    return render_template("login.html", tenant=tenant)


@auth_bp.post("/logout")
@auth_bp.post("/t/<slug>/logout")
@login_required
def logout(slug=None):
    slug = current_user.tenant.slug if current_user.tenant else None
    logout_user()
    session.clear()
    return redirect(url_for("auth.login", slug=slug) if slug else url_for("auth.login"))


@auth_bp.route("/password", methods=["GET", "POST"])
@auth_bp.route("/t/<slug>/password", methods=["GET", "POST"])
@login_required
def change_password(slug=None):
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        if not current_user.check_password(current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash("Password updated.", "ok")
            return redirect(_home_for(current_user))
    return render_template("password.html")


# ---------------------------------------------------------------- tenant home

@main_bp.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------- admin

@admin_bp.get("/")
@superadmin_required
def dashboard():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    stats = {
        "total": len(tenants),
        "active": sum(t.is_active for t in tenants),
        "users": User.query.filter(User.tenant_id.isnot(None)).count(),
        "paid": sum(t.plan != "starter" for t in tenants),
    }
    return render_template("admin/dashboard.html", tenants=tenants[:6], stats=stats)


@admin_bp.get("/tenants")
@superadmin_required
def tenants():
    q = request.args.get("q", "").strip()
    query = Tenant.query
    if q:
        like = f"%{q}%"
        query = query.filter(Tenant.name.ilike(like) | Tenant.slug.ilike(like) | Tenant.contact_email.ilike(like))
    return render_template("admin/tenants.html", tenants=query.order_by(Tenant.name).all(), q=q)


@admin_bp.route("/tenants/new", methods=["GET", "POST"])
@superadmin_required
def tenant_new():
    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        slug = form.get("slug", "").strip().lower()
        email = form.get("email", "").strip().lower()
        owner = form.get("owner", "").strip() or name
        plan = form.get("plan", "starter")
        error = None
        if not name:
            error = "Organisation name is required."
        elif not SLUG_RE.match(slug):
            error = "Slug must be 3-60 characters: lowercase letters, numbers and hyphens."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif plan not in PLANS:
            error = "Unknown plan."
        elif Tenant.query.filter_by(slug=slug).first():
            error = "That slug is already taken."
        elif User.query.filter_by(email=email).first():
            error = "A user with that email already exists."
        if error:
            flash(error, "error")
        else:
            temp = secrets.token_urlsafe(9)
            tenant = Tenant(name=name, slug=slug, contact_email=email,
                            phone=form.get("phone", "").strip() or None, plan=plan)
            user = User(tenant=tenant, email=email, name=owner, role="admin", must_change_password=True)
            user.set_password(temp)
            db.session.add_all([tenant, user])
            db.session.commit()
            return render_template("admin/tenant_created.html", tenant=tenant, user=user, temp=temp)
    return render_template("admin/tenant_form.html", form=form)


@admin_bp.get("/tenants/<int:tenant_id>")
@superadmin_required
def tenant_detail(tenant_id):
    tenant = db.get_or_404(Tenant, tenant_id)
    return render_template("admin/tenant_detail.html", tenant=tenant)


@admin_bp.post("/tenants/<int:tenant_id>/plan")
@superadmin_required
def tenant_plan(tenant_id):
    tenant = db.get_or_404(Tenant, tenant_id)
    plan = request.form.get("plan")
    if plan not in PLANS:
        abort(400)
    if len(tenant.users) > PLANS[plan]["max_users"]:
        flash(f"{tenant.name} has more users than the {PLANS[plan]['label']} plan allows.", "error")
    else:
        tenant.plan = plan
        db.session.commit()
        flash(f"{tenant.name} is now on the {PLANS[plan]['label']} plan.", "ok")
    return redirect(url_for("admin.tenant_detail", tenant_id=tenant.id))


@admin_bp.post("/tenants/<int:tenant_id>/toggle")
@superadmin_required
def tenant_toggle(tenant_id):
    tenant = db.get_or_404(Tenant, tenant_id)
    tenant.is_active = not tenant.is_active
    db.session.commit()
    flash(f"{tenant.name} {'activated' if tenant.is_active else 'suspended'}.", "ok")
    return redirect(url_for("admin.tenant_detail", tenant_id=tenant.id))


@admin_bp.post("/tenants/<int:tenant_id>/reset-password")
@superadmin_required
def tenant_reset(tenant_id):
    tenant = db.get_or_404(Tenant, tenant_id)
    owner = User.query.filter_by(tenant_id=tenant.id, role="admin").order_by(User.id).first_or_404()
    temp = secrets.token_urlsafe(9)
    owner.set_password(temp)
    owner.must_change_password = True
    owner.failed_attempts, owner.locked_until = 0, None
    db.session.commit()
    return render_template("admin/tenant_created.html", tenant=tenant, user=owner, temp=temp, reset=True)


@admin_bp.get("/system")
@superadmin_required
def system():
    counts = {
        p: Tenant.query.filter_by(plan=p).count() for p in PLAN_ORDER
    }
    return render_template("admin/system.html", version=VERSION, counts=counts,
                           db_name=db.engine.dialect.name)
