"""JSON API for the Android app.

The phone works offline: it keeps a copy of the products, clients and open debts, records sales, stock and payments
locally, and uploads them here when it is back online. Every change carries an `op_id` made on the phone; the result
of each change is stored (SyncOp), so an upload that is retried after a dropped connection never records anything
twice.

Endpoints
- POST /api/v1/login            {slug, email, password} -> {token, user, tenant}
- GET  /api/v1/catalog          -> products, clients, open debts (Bearer token)
- POST /api/v1/sync             {ops: [...]} -> per-op results and a fresh catalog (Bearer token)
- POST /t/<slug>/mobile-session  form token=... -> signs the app's web view in and opens the workspace
"""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import wraps

from flask import Blueprint, current_app, g, redirect, request, url_for
from flask_login import login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

from . import barcodes, db
from .models import Client, Product, Sale, SyncOp, Tenant, User, utcnow
from .payments import ONEMONEY_RE, normalise_msisdn
from .routes import _DUMMY_HASH, LOCK_MINUTES, MAX_ATTEMPTS
from .security import limiter

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")
mobile_bp = Blueprint("mobile", __name__)

TOKEN_DAYS = 90
MAX_OPS = 500


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="tylonerp-mobile-v1")


def make_token(user):
    # The password hash fingerprint means changing the password signs every phone out.
    return _serializer().dumps({"u": user.id, "p": user.password_hash[-16:]})


def user_from_token(token):
    try:
        data = _serializer().loads(token or "", max_age=TOKEN_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("u"))
    if not user or user.password_hash[-16:] != data.get("p") or not user.is_active or user.is_superadmin or not user.tenant:
        return None
    return user


def error(message, status=400, **extra):
    return {"ok": False, "error": message, **extra}, status


def api_user(view):
    """Bearer-token auth. Sets the request's current user so the workspace helpers work unchanged."""
    @wraps(view)
    def wrapped(*a, **kw):
        auth = request.headers.get("Authorization", "")
        user = user_from_token(auth[7:] if auth.startswith("Bearer ") else "")
        if not user:
            return error("Sign in again on this phone.", 401, signed_out=True)
        g._login_user = user  # Flask-Login reads current_user from here
        return view(user, *a, **kw)
    return wrapped


# ---------------------------------------------------------------- sign in

@api_bp.post("/login")
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"])
def login():
    j = request.get_json(silent=True) or {}
    slug = str(j.get("slug", "")).strip().lower()
    email = str(j.get("email", "")).strip().lower()
    password = str(j.get("password", ""))
    tenant = Tenant.query.filter_by(slug=slug).first() if slug else None
    user = User.query.filter_by(email=email).first() if email else None
    generic = "Incorrect business, email or password."
    if not tenant:
        check_password_hash(_DUMMY_HASH, password)
        return error(generic, 401)
    if user is None or user.is_locked():
        check_password_hash(_DUMMY_HASH, password)
        return error(generic, 401)
    if not user.check_password(password):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_ATTEMPTS:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        db.session.commit()
        return error(generic, 401)
    if user.tenant_id != tenant.id:
        return error(generic, 401)
    if not user.is_active:
        return error("This account or business is disabled. Contact your administrator.", 403)
    user.failed_attempts, user.locked_until, user.last_login = 0, None, utcnow()
    db.session.commit()
    return {"ok": True, "token": make_token(user), "user": _user_json(user), "tenant": _tenant_json(tenant),
            "must_change_password": user.must_change_password}


@mobile_bp.post("/t/<slug>/mobile-session")
def mobile_session(slug):
    """The app's web view posts its token here once, so the person is not asked to sign in twice."""
    user = user_from_token(request.form.get("token", ""))
    if not user or user.tenant.slug != slug:
        return redirect(url_for("auth.login", slug=slug))
    login_user(user)
    return redirect(url_for("ws.home", slug=slug))


def _user_json(u):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role}


def _tenant_json(t):
    b = t.branding
    from .regional import precision, symbol

    return {"id": t.id, "name": t.name, "slug": t.slug, "plan": t.plan_label, "accent": b.accent if b else None,
            "ecocash": bool(t.payment and t.payment.ecocash_enabled),
            "currency": t.currency_code, "locale": t.number_locale.replace("_", "-"), "decimals": precision(t.currency_code),
            "symbol": symbol(t.currency_code, t.number_locale), "timezone": t.tz, "language": t.language,
            "tax": {"name": t.tax_label, "rate": str(t.tax_percent), "inclusive": t.tax_is_inclusive}}


# ---------------------------------------------------------------- catalog

def _money(d):
    return str(Decimal(d).quantize(Decimal("0.01")))


def catalog_json(user):
    t = user.tenant
    products = Product.query.filter_by(tenant_id=t.id).order_by(Product.name).all()
    clients = Client.query.filter_by(tenant_id=t.id).order_by(Client.name).all()
    sales = Sale.query.filter(Sale.tenant_id == t.id, Sale.client_id.isnot(None)).order_by(Sale.created_at).all()
    debts = [s for s in sales if s.balance > 0]
    return {
        "server_time": utcnow().isoformat() + "Z",
        "tenant": _tenant_json(t), "user": _user_json(user),
        "products": [{"id": p.id, "name": p.name, "price": _money(p.price), "stock": p.stock, "barcode": p.barcode,
                      "sku": p.sku, "reorder_level": p.reorder_level} for p in products],
        "clients": [{"id": c.id, "name": c.name, "phone": c.phone} for c in clients],
        "debts": [{"id": s.id, "client_id": s.client_id, "client": s.client.name, "product": s.product_name,
                   "quantity": s.quantity, "total": _money(s.total), "balance": _money(s.balance),
                   "created_at": s.created_at.isoformat() + "Z"} for s in debts],
    }


@api_bp.get("/catalog")
@api_user
def catalog(user):
    return {"ok": True, **catalog_json(user)}


# ---------------------------------------------------------------- sync

class OpError(Exception):
    pass


def _resolve(ref, model, kind):
    """A reference from the phone: "s:<server id>", or "l:<op id>" for something the phone created offline."""
    from .workspace import tid

    ref = str(ref or "")
    if ref.startswith("s:"):
        obj = model.query.filter_by(id=int(ref[2:]) if ref[2:].isdigit() else -1, tenant_id=tid()).first()
    elif ref.startswith("l:"):
        op = SyncOp.query.filter_by(tenant_id=tid(), op_id=ref[2:]).first()
        sid = json.loads(op.result).get("server_id") if op else None
        obj = model.query.filter_by(id=sid, tenant_id=tid()).first() if sid else None
    else:
        obj = None
    if obj is None:
        raise OpError(f"The {kind} this refers to no longer exists.")
    return obj


def _when(ms):
    """Device time of the change, kept if it is plausible; otherwise now."""
    try:
        t = datetime.fromtimestamp(int(ms) / 1000, UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return utcnow()
    now = utcnow()
    return t if now - timedelta(days=60) <= t <= now + timedelta(minutes=10) else now


def op_client_create(d, op_id, user):
    from .workspace import tid, tidy_name

    name = tidy_name(d.get("name"))
    if not name:
        raise OpError("A client needs a name.")
    existing = Client.query.filter(Client.tenant_id == tid(), db.func.lower(Client.name) == name.lower()).first()
    if existing:
        return {"server_id": existing.id, "warning": f"{existing.name} was already a client; used the existing record."}
    c = Client(tenant_id=tid(), name=name, phone=(str(d.get("phone") or "").strip()[:40] or None),
               email=(str(d.get("email") or "").strip()[:255] or None))
    db.session.add(c)
    db.session.flush()
    return {"server_id": c.id}


def op_product_create(d, op_id, user):
    from .workspace import MAX_QTY, add_stock, integer, money, product_by_barcode, product_by_name, tid, tidy_name

    name, code = tidy_name(d.get("name")), barcodes.clean(d.get("barcode"))
    price = money(d.get("price"))
    qty = integer(d.get("stock"), None, MAX_QTY) if str(d.get("stock") or "").strip() else 0
    if qty is None:
        raise OpError("Quantity must be a whole number.")
    existing = (product_by_barcode(code) if code else None) or product_by_name(name)
    if existing:
        if code and existing.barcode and barcodes.key(existing.barcode) != barcodes.key(code):
            raise OpError(f"{existing.name} already has barcode {existing.barcode}.")
        if code and not existing.barcode:
            existing.barcode = code
        if qty:
            add_stock(existing, qty, "scan" if code else "restock", "Added on phone", ref=op_id)
        return {"server_id": existing.id, "warning": f"{existing.name} already existed; the stock was added to it."}
    if not name or price is None:
        raise OpError("A new product needs a name and a valid price.")
    p = Product(tenant_id=tid(), name=name, price=price, stock=0, barcode=code, sku=(str(d.get("sku") or "").strip()[:60] or None),
                method="barcode" if code else "manual", reorder_level=integer(d.get("reorder_level"), 5, MAX_QTY))
    db.session.add(p)
    db.session.flush()
    if qty:
        add_stock(p, qty, "new", "Registered on phone", ref=op_id)
    return {"server_id": p.id}


def op_stock_add(d, op_id, user):
    from .workspace import MAX_QTY, add_stock, integer

    p = _resolve(d.get("product"), Product, "product")
    qty = integer(d.get("quantity"), None, MAX_QTY)
    if not qty:
        raise OpError("Quantity must be a whole number above zero.")
    code = barcodes.clean(d.get("barcode"))
    if code and not p.barcode:
        p.barcode = code  # an unknown code the cashier linked to this product
    elif code and barcodes.key(p.barcode) != barcodes.key(code):
        raise OpError(f"{p.name} has barcode {p.barcode}, not {code}.")
    m = add_stock(p, qty, "scan" if d.get("source") == "scan" else "restock", "Added on phone", ref=op_id)
    return {"server_id": p.id, "movement": m.id, "stock": p.stock}


def op_sale_create(d, op_id, user):
    from .workspace import MAX_QTY, integer, money, tid

    p = _resolve(d.get("product"), Product, "product")
    qty = integer(d.get("quantity"), None, MAX_QTY)
    if not qty:
        raise OpError("Quantity must be a whole number above zero.")
    unit = money(d.get("unit_price"))
    unit = p.price if unit is None else unit
    total = unit * qty
    paid = total if str(d.get("paid") or "").strip() == "" else money(d.get("paid"))
    if paid is None:
        raise OpError("The amount paid is not a valid amount.")
    paid = min(paid, total)
    client = _resolve(d.get("client"), Client, "client") if d.get("client") else None
    if paid < total and not client:
        raise OpError("A part-paid or credit sale needs a client.")
    method = d.get("method") if d.get("method") in ("cash", "onemoney") else "cash"
    sale = Sale(tenant_id=tid(), client=client, product_id=p.id, product_name=p.name, quantity=qty, unit_price=unit,
                paid=paid, created_by=user.id, payment_method=method, created_at=_when(d.get("at")))
    if method == "onemoney":
        phone, ref = normalise_msisdn(d.get("phone")), str(d.get("payment_ref") or "").strip()[:60]
        if not ONEMONEY_RE.match(phone) or not ref:
            raise OpError("A OneMoney sale needs the customer's OneMoney number and the transaction code.")
        sale.payment_phone, sale.payment_ref, sale.payment_status = phone, ref, "paid"
    p.stock -= qty
    db.session.add(sale)
    db.session.flush()
    out = {"server_id": sale.id, "stock": p.stock}
    if p.stock < 0:
        out["warning"] = f"{p.name} is now at {p.stock}: more were sold than the system had. Count it and add stock."
    return out


def op_payment_create(d, op_id, user):
    from .workspace import money

    s = _resolve(d.get("sale"), Sale, "sale")
    amount = money(d.get("amount"))
    if not amount:
        raise OpError("Enter an amount above zero.")
    if s.settled or s.balance <= 0:
        raise OpError("Nothing is owed on that sale any more.")
    out = {"server_id": s.id}
    if amount > s.balance:
        out["warning"] = f"Only {s.balance} was owed, so {s.balance} was recorded instead of {amount}."
        amount = s.balance
    s.paid += amount
    out["balance"] = _money(s.balance)
    return out


OPS = {"client.create": op_client_create, "product.create": op_product_create, "stock.add": op_stock_add,
       "sale.create": op_sale_create, "payment.create": op_payment_create}


def apply_op(op, user):
    from .workspace import tid

    op_id = str(op.get("op_id") or "").strip()[:40]
    kind = str(op.get("kind") or "")
    if not op_id:
        return {"op_id": "", "ok": False, "error": "Missing op_id."}
    done = SyncOp.query.filter_by(tenant_id=tid(), op_id=op_id).first()
    if done:
        return {**json.loads(done.result), "op_id": op_id, "repeat": True}
    handler = OPS.get(kind)
    try:
        if not handler:
            raise OpError(f"Unknown change type {kind!r}.")
        result = {"ok": True, **handler(op.get("data") or {}, op_id, user)}
    except OpError as e:
        db.session.rollback()
        result = {"ok": False, "error": str(e)}
    except Exception:
        db.session.rollback()
        current_app.logger.exception("sync op %s failed", op_id)
        result = {"ok": False, "error": "The server could not save this change.", "retry": True}
        return {**result, "op_id": op_id}  # not stored, so the phone tries again later
    db.session.add(SyncOp(tenant_id=tid(), op_id=op_id, kind=kind[:30], user_id=user.id, result=json.dumps(result)))
    try:
        db.session.commit()
    except Exception:  # the same op arrived twice at once; the other request stored it
        db.session.rollback()
        done = SyncOp.query.filter_by(tenant_id=tid(), op_id=op_id).first()
        if done:
            return {**json.loads(done.result), "op_id": op_id, "repeat": True}
        return {"op_id": op_id, "ok": False, "error": "Try again.", "retry": True}
    return {**result, "op_id": op_id}


@api_bp.post("/sync")
@api_user
def sync(user):
    j = request.get_json(silent=True) or {}
    ops = j.get("ops") or []
    if not isinstance(ops, list):
        return error("ops must be a list.")
    if len(ops) > MAX_OPS:
        return error(f"Send at most {MAX_OPS} changes at a time.", 413)
    results = [apply_op(op if isinstance(op, dict) else {}, user) for op in ops]
    return {"ok": True, "results": results, "catalog": catalog_json(user)}
