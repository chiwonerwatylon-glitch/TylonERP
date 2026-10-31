from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

PLANS = {
    "starter": {"label": "Starter", "max_users": 3, "price": 0},
    "growth": {"label": "Growth", "max_users": 15, "price": 29},
    "enterprise": {"label": "Enterprise", "max_users": 200, "price": 99},
}
PLAN_ORDER = list(PLANS)


class Tenant(db.Model):
    __tablename__ = "tenants"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(60), unique=True, nullable=False, index=True)
    contact_email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(40))
    plan = db.Column(db.String(20), nullable=False, default="starter")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    trial_ends_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    users = db.relationship("User", backref="tenant", cascade="all, delete-orphan")

    @property
    def max_users(self):
        return PLANS[self.plan]["max_users"]

    @property
    def plan_label(self):
        return PLANS[self.plan]["label"]

    @property
    def next_plan(self):
        i = PLAN_ORDER.index(self.plan)
        return PLAN_ORDER[i + 1] if i + 1 < len(PLAN_ORDER) else None


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="staff")  # superadmin, admin, staff
    is_active_flag = db.Column("is_active", db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def is_active(self):  # Flask-Login hook
        return self.is_active_flag and (self.tenant is None or self.tenant.is_active)

    @property
    def is_superadmin(self):
        return self.role == "superadmin"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
