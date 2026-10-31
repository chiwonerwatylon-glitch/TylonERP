"""Tenant workspace: dashboard, stock, clients, sales, debtors, members, branding."""
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

import re

from flask import (Blueprint, Response, abort, g, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from . import db
from .models import Client, Product, Sale, Tenant, TenantBranding, User
from .routes import EMAIL_RE

ws_bp = Blueprint("ws", __name__, url_prefix="/t/<slug>/app")
public_bp = Blueprint("tenant_public", __name__)

MAX_IMAGE = 2 * 1024 * 1024
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@ws_bp.url_value_preprocessor
def _pop_slug(endpoint, values):
    if values:
        g.slug = values.pop("slug", None)


def tenant_user(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if current_user.is_superadmin or current_user.tenant is None:
            return redirect(url_for("admin.dashboard"))
        if current_user.tenant.slug != g.slug:
            abort(404)
        if current_user.must_change_password:
            return redirect(url_for("auth.change_password"))
        return view(*a, **kw)
    return wrapped


def tenant_admin(view):
    @wraps(view)
    @tenant_user
    def wrapped(*a, **kw):
        if current_user.role != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def tid():
    return current_user.tenant_id


def money(v, default=None):
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, AttributeError):
        return default
    return d if d >= 0 else default


def integer(v, default=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


# ------------------------------------------------------------ public tenant login page

def _branding(tenant):
    return tenant.branding


@public_bp.get("/t/<slug>/logo")
def login_logo(slug):
    t = Tenant.query.filter_by(slug=slug).first_or_404()
    b = t.branding
    if not b or not b.logo:
        abort(404)
    return Response(b.logo, mimetype=b.logo_mime, headers={"Cache-Control": "public, max-age=300"})


@public_bp.get("/t/<slug>/image")
def login_image(slug):
    t = Tenant.query.filter_by(slug=slug).first_or_404()
    b = t.branding
    if not b or not b.image:
        abort(404)
    return Response(b.image, mimetype=b.image_mime, headers={"Cache-Control": "public, max-age=300"})


# ------------------------------------------------------------ dashboard

@ws_bp.get("/")
@tenant_user
def home():
    t = current_user.tenant
    today = datetime.utcnow() - timedelta(days=30)
    sales = Sale.query.filter_by(tenant_id=tid()).all()
    recent = [s for s in sales if s.created_at >= today]
    low = Product.query.filter(Product.tenant_id == tid(), Product.stock <= Product.reorder_level).order_by(Product.stock).limit(6).all()
    stats = {
        "revenue": sum((s.total for s in recent), Decimal(0)),
        "owed": sum((s.balance for s in sales), Decimal(0)),
        "products": Product.query.filter_by(tenant_id=tid()).count(),
        "clients": Client.query.filter_by(tenant_id=tid()).count(),
    }
    latest = Sale.query.filter_by(tenant_id=tid()).order_by(Sale.created_at.desc()).limit(6).all()
    return render_template("ws/home.html", tenant=t, stats=stats, low=low, latest=latest)


# ------------------------------------------------------------ products

MAX_PHOTO = 1024 * 1024
SIG_RE = re.compile(r"^[0-9a-f]{70}$")
DUPLICATE_SCORE = 0.12  # lower = more alike; below this a photo counts as the same product


def _sniff(data):
    mime = next((m for sig, m in IMAGE_TYPES.items() if data.startswith(sig)), None)
    if mime == "image/webp" and data[8:12] != b"WEBP":
        return None
    return mime


def signature_score(a, b):
    """0 = identical look, 1 = completely different. Mixes shape (dHash) and colour."""
    if not a or not b or len(a) != 70 or len(b) != 70:
        return 1.0
    shape = bin(int(a[:16], 16) ^ int(b[:16], 16)).count("1") / 64
    ca = [int(a[16 + i:18 + i], 16) for i in range(0, 54, 2)]
    cb = [int(b[16 + i:18 + i], 16) for i in range(0, 54, 2)]
    colour = sum(abs(x - y) for x, y in zip(ca, cb)) / (54 * 255)
    return 0.4 * shape + 0.6 * min(1.0, colour * 3)


def _product_json(p, score=None):
    d = {"id": p.id, "name": p.name, "price": str(p.price), "stock": p.stock,
         "method": p.method, "scent": p.scent, "barcode": p.barcode,
         "photo": url_for("ws.product_photo", pid=p.id) if p.photo else None}
    if score is not None:
        d["match"] = max(0, round((1 - score) * 100))
    return d


def _best_matches(sig, limit=5):
    scored = [(signature_score(sig, p.signature), p)
              for p in Product.query.filter(Product.tenant_id == tid(), Product.signature.isnot(None)).all()]
    scored.sort(key=lambda t: t[0])
    return [(sc, p) for sc, p in scored[:limit] if sc < 0.45]


@ws_bp.get("/products/<int:pid>/photo")
@tenant_user
def product_photo(pid):
    p = Product.query.filter_by(id=pid, tenant_id=tid()).first_or_404()
    if not p.photo:
        abort(404)
    return Response(p.photo, mimetype=p.photo_mime, headers={"Cache-Control": "private, max-age=300"})


@ws_bp.route("/products", methods=["GET", "POST"])
@tenant_user
def products():
    if request.method == "POST":
        f = request.form
        method = f.get("method", "photo")
        name = f.get("name", "").strip()
        price = money(f.get("price"))
        stock = integer(f.get("stock"), 0)
        barcode = f.get("barcode", "").strip() or None
        scent = f.get("scent", "").strip() or None
        sig = f.get("signature", "").strip().lower() or None
        file = request.files.get("photo")
        data = file.read(MAX_PHOTO + 1) if file and file.filename else b""
        error = None
        if method not in ("barcode", "photo", "scent"):
            error = "Choose how this product is recognised."
        elif not name or price is None:
            error = "Product name and a valid price are required."
        elif method == "barcode" and not barcode:
            error = "Scan or type the barcode."
        elif method == "scent" and not scent:
            error = "Describe the scent."
        elif method in ("photo", "scent") and not data:
            error = "Take a photo of the product."
        elif data and (len(data) > MAX_PHOTO or not _sniff(data)):
            error = "The photo must be a PNG, JPEG or WebP under 1 MB."
        elif sig and not SIG_RE.match(sig):
            error = "Photo signature is invalid. Take the photo again."
        elif method in ("photo", "scent") and not sig:
            error = "Photo could not be analysed. Take the photo again."
        elif barcode and Product.query.filter_by(tenant_id=tid(), barcode=barcode).first():
            dup = Product.query.filter_by(tenant_id=tid(), barcode=barcode).first()
            error = f"Barcode {barcode} already belongs to {dup.name}. Add stock to it instead."
        elif sig and method != "barcode":
            near = _best_matches(sig, 1)
            if near and near[0][0] < DUPLICATE_SCORE:
                error = f"This looks like {near[0][1].name}, which is already registered. Add stock to it instead."
        if error:
            flash(error, "error")
        else:
            db.session.add(Product(tenant_id=tid(), name=name, price=price, stock=stock, method=method,
                                   barcode=barcode, scent=scent, sku=f.get("sku", "").strip() or None,
                                   photo=data or None, photo_mime=_sniff(data) if data else None,
                                   signature=sig, reorder_level=integer(f.get("reorder_level"), 5)))
            try:
                db.session.commit()
                flash("Product added.", "ok")
            except Exception:
                db.session.rollback()
                flash("That barcode is already registered.", "error")
        return redirect(url_for("ws.products"))
    items = Product.query.filter_by(tenant_id=tid()).order_by(Product.name).all()
    return render_template("ws/products.html", items=items)


@ws_bp.post("/products/scan-in")
@tenant_user
def scan_in():
    """Counting stock in by barcode: each scan of a known code adds one unit.

    An unknown code creates the product (name and price required) with one unit.
    A code never creates a second product.
    """
    j = request.get_json(silent=True) or {}
    code = str(j.get("barcode", "")).strip()[:64]
    if not code:
        return {"error": "No barcode received."}, 400
    p = Product.query.filter_by(tenant_id=tid(), barcode=code).first()
    if p:
        p.stock += 1
        db.session.commit()
        return {"found": True, "product": _product_json(p)}
    name, price = str(j.get("name", "")).strip(), money(j.get("price"))
    if not name or price is None:
        return {"found": False, "barcode": code}
    p = Product(tenant_id=tid(), name=name, price=price, stock=1, method="barcode", barcode=code,
                reorder_level=5)
    db.session.add(p)
    try:
        db.session.commit()
    except Exception:  # lost a race with another scanner
        db.session.rollback()
        p = Product.query.filter_by(tenant_id=tid(), barcode=code).first_or_404()
        p.stock += 1
        db.session.commit()
        return {"found": True, "product": _product_json(p)}
    return {"found": True, "created": True, "product": _product_json(p)}


# ------------------------------------------------------------ quick sell

@ws_bp.get("/quick-sell")
@tenant_user
def quick_sell():
    clients = Client.query.filter_by(tenant_id=tid()).order_by(Client.name).all()
    return render_template("ws/quick_sell.html", clients=clients)


@ws_bp.post("/quick-sell/match")
@tenant_user
def quick_match():
    j = request.get_json(silent=True) or {}
    code = str(j.get("barcode", "")).strip()
    if code:
        p = Product.query.filter_by(tenant_id=tid(), barcode=code).first()
        if not p:
            return {"matches": [], "message": f"No product has barcode {code}."}
        return {"matches": [_product_json(p, 0.0)]}
    sig = str(j.get("signature", "")).strip().lower()
    if not SIG_RE.match(sig):
        return {"error": "Could not read the picture. Try again."}, 400
    matches = _best_matches(sig)
    if not matches:
        return {"matches": [], "message": "No registered product looks like this. Try a clearer photo."}
    return {"matches": [_product_json(p, sc) for sc, p in matches]}


@ws_bp.post("/quick-sell/confirm")
@tenant_user
def quick_confirm():
    j = request.get_json(silent=True) or {}
    p = Product.query.filter_by(id=integer(j.get("product_id"), -1), tenant_id=tid()).with_for_update().first()
    qty = integer(j.get("quantity"))
    if not p:
        return {"error": "Product not found."}, 404
    if not qty:
        return {"error": "Enter how many to sell."}, 400
    if qty > p.stock:
        return {"error": f"Only {p.stock} of {p.name} left in stock."}, 409
    client = None
    if j.get("client_id"):
        client = Client.query.filter_by(id=integer(j.get("client_id"), -1), tenant_id=tid()).first()
    total = p.price * qty
    paid = money(j.get("paid"), total) if str(j.get("paid", "")).strip() else total
    paid = min(paid, total)
    if paid < total and not client:
        return {"error": "Choose a client for a part-paid or credit sale."}, 400
    p.stock -= qty
    sale = Sale(tenant_id=tid(), client=client, product_id=p.id, product_name=p.name,
                quantity=qty, unit_price=p.price, paid=paid, created_by=current_user.id)
    db.session.add(sale)
    db.session.commit()
    return {"ok": True, "total": str(total), "stock": p.stock, "name": p.name,
            "receipt": url_for("ws.receipt", sid=sale.id, print=1, back="quick")}


@ws_bp.post("/products/<int:pid>/restock")
@tenant_user
def restock(pid):
    p = Product.query.filter_by(id=pid, tenant_id=tid()).first_or_404()
    qty = integer(request.form.get("qty"))
    if not qty:
        flash("Enter a quantity greater than zero.", "error")
    else:
        p.stock += qty
        db.session.commit()
        flash(f"Added {qty} to {p.name}.", "ok")
    return redirect(url_for("ws.products"))


@ws_bp.post("/products/<int:pid>/delete")
@tenant_admin
def product_delete(pid):
    p = Product.query.filter_by(id=pid, tenant_id=tid()).first_or_404()
    db.session.delete(p)
    db.session.commit()
    flash("Product removed.", "ok")
    return redirect(url_for("ws.products"))


# ------------------------------------------------------------ clients

@ws_bp.route("/clients", methods=["GET", "POST"])
@tenant_user
def clients():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            flash("Client name is required.", "error")
        else:
            db.session.add(Client(tenant_id=tid(), name=name, email=f.get("email", "").strip() or None,
                                  phone=f.get("phone", "").strip() or None))
            db.session.commit()
            flash("Client added.", "ok")
        return redirect(url_for("ws.clients"))
    items = Client.query.filter_by(tenant_id=tid()).order_by(Client.name).all()
    return render_template("ws/clients.html", items=items)


# ------------------------------------------------------------ sales

@ws_bp.route("/sales", methods=["GET", "POST"])
@tenant_user
def sales():
    if request.method == "POST":
        f = request.form
        p = Product.query.filter_by(id=integer(f.get("product_id"), -1), tenant_id=tid()).first()
        qty = integer(f.get("quantity"))
        client = None
        if f.get("client_id"):
            client = Client.query.filter_by(id=integer(f.get("client_id"), -1), tenant_id=tid()).first()
        error = None
        if not p:
            error = "Choose a product."
        elif not qty:
            error = "Quantity must be at least 1."
        elif qty > p.stock:
            error = f"Only {p.stock} of {p.name} in stock."
        if error:
            flash(error, "error")
        else:
            total = p.price * qty
            paid = money(f.get("paid"), total) if f.get("paid", "").strip() else total
            paid = min(paid, total)
            if paid < total and not client:
                flash("Choose a client for a part-paid or credit sale.", "error")
                return redirect(url_for("ws.sales"))
            p.stock -= qty
            sale = Sale(tenant_id=tid(), client=client, product_id=p.id, product_name=p.name,
                        quantity=qty, unit_price=p.price, paid=paid, created_by=current_user.id)
            db.session.add(sale)
            db.session.commit()
            return redirect(url_for("ws.receipt", sid=sale.id, print=1, back="sales"))
        return redirect(url_for("ws.sales"))

    kind = request.args.get("type", "all")
    query = Sale.query.filter_by(tenant_id=tid())
    if kind == "cash":
        query = query.filter(Sale.paid >= Sale.quantity * Sale.unit_price)
    elif kind == "credit":
        query = query.filter(Sale.paid < Sale.quantity * Sale.unit_price)
    else:
        kind = "all"
    page = max(1, integer(request.args.get("page"), 1))
    per_page = 50
    everything = query.order_by(Sale.created_at.desc(), Sale.id.desc())
    total_rows = everything.count()
    items = everything.offset((page - 1) * per_page).limit(per_page).all()
    all_sales = query.all()
    summary = {
        "count": total_rows,
        "total": sum((x.total for x in all_sales), Decimal(0)),
        "paid": sum((x.paid for x in all_sales), Decimal(0)),
        "owed": sum((x.balance for x in all_sales), Decimal(0)),
    }
    base = Sale.query.filter_by(tenant_id=tid())
    counts = {"all": base.count(),
              "cash": base.filter(Sale.paid >= Sale.quantity * Sale.unit_price).count()}
    counts["credit"] = counts["all"] - counts["cash"]
    ids = [i for (i,) in db.session.query(Sale.id).filter_by(tenant_id=tid()).order_by(Sale.id)]
    numbers = {sid: n for n, sid in enumerate(ids, 1)}
    return render_template(
        "ws/sales.html", items=items, numbers=numbers, kind=kind, page=page, pages=max(1, -(-total_rows // per_page)),
        summary=summary, counts=counts,
        products=Product.query.filter(Product.tenant_id == tid(), Product.stock > 0).order_by(Product.name).all(),
        clients=Client.query.filter_by(tenant_id=tid()).order_by(Client.name).all(),
    )


@ws_bp.get("/sales/<int:sid>/receipt")
@tenant_user
def receipt(sid):
    s = Sale.query.filter_by(id=sid, tenant_id=tid()).first_or_404()
    number = Sale.query.filter(Sale.tenant_id == tid(), Sale.id <= s.id).count()
    cashier = db.session.get(User, s.created_by) if s.created_by else None
    return render_template("ws/receipt.html", s=s, number=number, tenant=current_user.tenant,
                           cashier=cashier, autoprint=bool(request.args.get("print")),
                           back=request.args.get("back", "sales"))


# ------------------------------------------------------------ debtors

@ws_bp.get("/debtors")
@tenant_user
def debtors():
    open_sales = [s for s in Sale.query.filter_by(tenant_id=tid()).order_by(Sale.created_at).all()
                  if s.balance > 0 and s.client]
    return render_template("ws/debtors.html", items=open_sales,
                           total=sum((s.balance for s in open_sales), Decimal(0)))


@ws_bp.post("/sales/<int:sid>/payment")
@tenant_user
def payment(sid):
    s = Sale.query.filter_by(id=sid, tenant_id=tid()).first_or_404()
    amt = money(request.form.get("amount"))
    if not amt or amt > s.balance:
        flash(f"Enter an amount up to {s.balance}.", "error")
    else:
        s.paid += amt
        db.session.commit()
        flash("Payment recorded.", "ok")
    return redirect(url_for("ws.debtors"))


# ------------------------------------------------------------ members

@ws_bp.route("/members", methods=["GET", "POST"])
@tenant_admin
def members():
    t = current_user.tenant
    created = None
    if request.method == "POST":
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        role = f.get("role", "staff")
        error = None
        if not name:
            error = "Name is required."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif role not in ("admin", "staff"):
            error = "Unknown role."
        elif len(t.users) >= t.max_users:
            error = f"The {t.plan_label} plan allows {t.max_users} members. Ask your administrator to upgrade."
        elif User.query.filter_by(email=email).first():
            error = "A user with that email already exists."
        if error:
            flash(error, "error")
        else:
            temp = secrets.token_urlsafe(9)
            u = User(tenant_id=t.id, email=email, name=name, role=role, must_change_password=True)
            u.set_password(temp)
            db.session.add(u)
            db.session.commit()
            created = (u, temp)
    return render_template("ws/members.html", tenant=t, users=sorted(t.users, key=lambda u: u.name.lower()), created=created)


def _member(uid):
    u = User.query.filter_by(id=uid, tenant_id=tid()).first_or_404()
    if u.id == current_user.id:
        abort(400)
    return u


@ws_bp.post("/members/<int:uid>/toggle")
@tenant_admin
def member_toggle(uid):
    u = _member(uid)
    u.is_active_flag = not u.is_active_flag
    db.session.commit()
    flash(f"{u.name} {'activated' if u.is_active_flag else 'deactivated'}.", "ok")
    return redirect(url_for("ws.members"))


@ws_bp.post("/members/<int:uid>/reset")
@tenant_admin
def member_reset(uid):
    u = _member(uid)
    temp = secrets.token_urlsafe(9)
    u.set_password(temp)
    u.must_change_password = True
    u.failed_attempts, u.locked_until = 0, None
    db.session.commit()
    t = current_user.tenant
    return render_template("ws/members.html", tenant=t, users=sorted(t.users, key=lambda x: x.name.lower()), created=(u, temp), reset=True)


# ------------------------------------------------------------ branding

@ws_bp.route("/branding", methods=["GET", "POST"])
@tenant_admin
def branding():
    t = current_user.tenant
    b = t.branding
    if request.method == "POST":
        if b is None:
            b = TenantBranding(tenant_id=t.id)
            db.session.add(b)
        for field in ("accent", "background", "panel"):
            val = request.form.get(field, "").strip()
            if request.form.get("reset_colours"):
                val = ""
            if val and not HEX.match(val):
                flash("Colours must look like #d4af6a.", "error")
                db.session.rollback()
                return redirect(url_for("ws.branding"))
            setattr(b, field, val.lower() or None)
        b.headline = request.form.get("headline", "").strip()[:120] or None
        b.tagline = request.form.get("tagline", "").strip()[:240] or None
        for kind in ("image", "logo"):
            if request.form.get(f"remove_{kind}"):
                setattr(b, kind, None)
                setattr(b, f"{kind}_mime", None)
            file = request.files.get(kind)
            if file and file.filename:
                data = file.read(MAX_IMAGE + 1)
                mime = next((m for sig, m in IMAGE_TYPES.items() if data.startswith(sig)), None)
                if mime == "image/webp" and data[8:12] != b"WEBP":
                    mime = None
                if len(data) > MAX_IMAGE:
                    flash("Pictures must be 2 MB or smaller.", "error")
                    db.session.rollback()
                    return redirect(url_for("ws.branding"))
                if not mime:
                    flash("Use a PNG, JPEG or WebP picture.", "error")
                    db.session.rollback()
                    return redirect(url_for("ws.branding"))
                setattr(b, kind, data)
                setattr(b, f"{kind}_mime", mime)
        db.session.commit()
        flash("Login page updated.", "ok")
        return redirect(url_for("ws.branding"))
    return render_template("ws/branding.html", tenant=t, b=b)
