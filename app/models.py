from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy.orm import joinedload
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
    return db.session.get(User, int(user_id), options=[joinedload(User.tenant)])


class TenantBranding(db.Model):
    """Per-tenant login look. Image bytes live in the DB so they survive redeploys."""
    __tablename__ = "tenant_branding"
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    headline = db.Column(db.String(120))
    tagline = db.Column(db.String(240))
    image = db.Column(db.LargeBinary)
    image_mime = db.Column(db.String(40))
    logo = db.Column(db.LargeBinary)
    logo_mime = db.Column(db.String(40))
    accent = db.Column(db.String(7))
    background = db.Column(db.String(7))
    panel = db.Column(db.String(7))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant = db.relationship("Tenant", backref=db.backref("branding", uselist=False, cascade="all, delete-orphan"))


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(60))
    price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # How the product is recognised: barcode, photo or scent
    method = db.Column(db.String(10), default="photo")
    barcode = db.Column(db.String(64))
    scent = db.Column(db.String(120))
    photo = db.Column(db.LargeBinary)
    photo_mime = db.Column(db.String(40))
    signature = db.Column(db.String(70))  # 16 hex dHash + 54 hex colour grid

    __table_args__ = (db.Index("uq_product_barcode", "tenant_id", "barcode", unique=True),)


class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sales = db.relationship("Sale", backref="client")

    @property
    def balance(self):
        return sum((s.balance for s in self.sales), 0)


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    product_name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    paid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    @property
    def total(self):
        return self.quantity * self.unit_price

    @property
    def balance(self):
        return self.total - self.paid

    @property
    def kind(self):
        """Cash = paid in full, Credit = nothing paid, Part-paid in between."""
        if self.paid >= self.total:
            return "Cash"
        return "Credit" if self.paid <= 0 else "Part-paid"
