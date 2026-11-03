"""Tenant workspace: dashboard, stock, clients, sales, debtors, members, branding."""
import csv
import io
import re
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import barcodes, db
from .models import Client, Product, Sale, StockMovement, Tenant, TenantBranding, TenantPayment, User, utcnow
from .payments import (
    ECOCASH_RE,
    ONEMONEY_RE,
    EcoCashError,
    EcoCashUnknown,
    client_for_tenant,
    new_correlator,
    normalise_msisdn,
)
from .regional import local_now, to_local
from .routes import EMAIL_RE
from .secrets import encrypt

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


MAX_MONEY = Decimal("9999999999.99")  # Numeric(12, 2)
MAX_QTY = 1_000_000  # largest quantity accepted in one go


def money(v, default=None):
    """Parse a non-negative amount with at most two decimals. 'NaN', 'Infinity' and huge numbers are rejected."""
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, AttributeError, ValueError):
        return default
    if not d.is_finite() or d < 0:
        return default
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return d if d <= MAX_MONEY else default


def integer(v, default=None, maximum=2_000_000_000):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return default
    return n if 0 <= n <= maximum else default


def add_stock(p, qty, source, note=None, ref=None):
    """Increase a product's stock and keep a record of where it came from. Returns the record."""
    p.stock += qty
    m = StockMovement(tenant_id=p.tenant_id, product=p, quantity=qty, source=source,
                      note=(note or "")[:120] or None, created_by=current_user.id, client_ref=ref)
    db.session.add(m)
    db.session.flush()
    return m


METHODS = ("cash", "ecocash", "onemoney")


def ecocash():
    return client_for_tenant(current_app.extensions["settings"], current_user.tenant)


def complete_sale(p, qty, client, paid_raw, method, phone_raw, ref):
    """Create the sale, take mobile-money payment if asked, and return (sale, error, warning).

    Cash keeps the old behaviour. EcoCash charges the customer's wallet (they approve with their PIN) and
    only keeps the sale if the charge succeeds. OneMoney (NetOne) has no integration yet: the cashier
    confirms the payment on the customer's phone and records the NetOne transaction code.
    """
    method = method if method in METHODS else "cash"
    total = p.price * qty
    paid = money(paid_raw, total) if str(paid_raw or "").strip() else total
    paid = min(paid, total)
    if paid < total and not client:
        return None, "Choose a client for a part-paid or credit sale.", None
    phone = normalise_msisdn(phone_raw)
    if method == "ecocash":
        gateway = ecocash()
        if not gateway.enabled:
            return None, "EcoCash is not set up for this business yet. An admin can add the merchant details under Payments.", None
        if not ECOCASH_RE.match(phone):
            return None, "Enter the customer's EcoCash number, for example 0771234567.", None
        if paid <= 0:
            return None, "Enter an amount above zero to charge.", None
    elif method == "onemoney":
        ref = (ref or "").strip()[:60]
        if not ONEMONEY_RE.match(phone):
            return None, "Enter the customer's OneMoney number, for example 0711234567.", None
        if not ref:
            return None, "Enter the OneMoney transaction code from the confirmation message.", None
        if paid <= 0:
            return None, "Enter an amount above zero.", None

    p.stock -= qty
    sale = Sale(tenant_id=tid(), client=client, product_id=p.id, product_name=p.name, quantity=qty,
                unit_price=p.price, paid=paid if method in ("cash", "onemoney") else 0,
                created_by=current_user.id, payment_method=method)
    if method == "onemoney":
        sale.payment_phone, sale.payment_ref, sale.payment_status = phone, ref, "paid"
    db.session.add(sale)
    if method != "ecocash":
        db.session.commit()
        return sale, None, None

    # Save as pending first so a crash or timeout can never lose track of a charge.
    sale.payment_phone, sale.payment_status = phone, "pending"
    db.session.flush()
    sale.payment_correlator = new_correlator(tid(), sale.id)
    db.session.commit()
    try:
        res = gateway.charge(phone, paid, sale.payment_correlator, f"SALE-{tid()}-{sale.id}", p.name)
    except EcoCashError as e:
        _undo_sale(sale, p, qty)
        return None, f"EcoCash payment failed: {e}", None
    except EcoCashUnknown:
        return sale, None, ("EcoCash did not answer, so the payment is unconfirmed. "
                            "Use Check payment on the Sales page before handing over the goods.")
    if not res.ok:
        _undo_sale(sale, p, qty)
        return None, "EcoCash did not take the payment.", None
    sale.paid, sale.payment_status, sale.payment_ref = paid, "paid", res.ecocash_reference
    db.session.commit()
    return sale, None, None


def _undo_sale(sale, p, qty):
    p.stock += qty
    db.session.delete(sale)
    db.session.commit()


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
    now = utcnow()
    since = now - timedelta(days=30)
    sales = Sale.query.filter_by(tenant_id=tid()).all()
    counted = [s for s in sales if s.payment_status != "refunded"]
    recent = [s for s in counted if s.created_at >= since]
    low = Product.query.filter(Product.tenant_id == tid(), Product.stock <= Product.reorder_level).order_by(Product.stock).limit(6).all()
    stats = {
        "revenue": sum((s.total for s in recent), Decimal(0)),
        "owed": sum((s.balance for s in sales), Decimal(0)),
        "debtors": len({s.client_id for s in sales if s.balance > 0 and s.client_id}),
        "products": Product.query.filter_by(tenant_id=tid()).count(),
        "clients": Client.query.filter_by(tenant_id=tid()).count(),
        "low": Product.query.filter(Product.tenant_id == tid(), Product.stock <= Product.reorder_level).count(),
    }
    # Takings per day for the last 14 days, in the business's own time zone, oldest first, for the bar chart.
    today = local_now(t.tz).date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    by_day = dict.fromkeys(days, Decimal(0))
    local_day = {s.id: to_local(s.created_at, t.tz).date() for s in counted}
    for s in counted:
        d = local_day[s.id]
        if d in by_day:
            by_day[d] += s.total
    takings = [{"day": d, "total": by_day[d]} for d in days]
    stats["today"] = by_day[today]
    stats["today_count"] = len({(s.order_id or -s.id) for s in counted if local_day[s.id] == today})
    latest = Sale.query.filter_by(tenant_id=tid()).order_by(Sale.created_at.desc()).limit(6).all()
    return render_template("ws/home.html", tenant=t, stats=stats, low=low, latest=latest, takings=takings,
                           peak=max((x["total"] for x in takings), default=Decimal(0)))


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


def tidy_name(raw):
    """Product names are compared ignoring case and repeated spaces, so tidy them the same way on save."""
    return " ".join(str(raw or "").split())[:150]


def product_by_barcode(code, lock=False):
    """The tenant's product with this barcode, however the code was read or stored."""
    forms = barcodes.variants(code)
    if not forms:
        return None
    q = Product.query.filter(Product.tenant_id == tid(), Product.barcode.in_(forms))
    if lock:
        q = q.with_for_update()
    found = q.all()
    return next((p for p in found if p.barcode == code), found[0] if found else None)


def product_by_name(name):
    name = tidy_name(name).lower()
    if not name:
        return None
    return Product.query.filter(Product.tenant_id == tid(), db.func.lower(Product.name) == name).first()


def duplicate_groups():
    """Products that look like the same thing: same name (ignoring case and spaces) or the same barcode."""
    groups, seen = [], set()
    items = Product.query.filter_by(tenant_id=tid()).order_by(Product.id).all()
    for keyfn in (lambda p: tidy_name(p.name).lower(), lambda p: barcodes.key(p.barcode)):
        buckets = {}
        for p in items:
            k = keyfn(p)
            if k:
                buckets.setdefault(k, []).append(p)
        for group in buckets.values():
            ids = frozenset(p.id for p in group)
            if len(group) > 1 and ids not in seen:
                seen.add(ids)
                groups.append(group)
    return groups


@ws_bp.route("/products", methods=["GET", "POST"])
@tenant_user
def products():
    if request.method == "POST":
        f = request.form
        method = f.get("method", "photo")
        name = tidy_name(f.get("name"))
        price = money(f.get("price"))
        stock = integer(f.get("stock"), None, MAX_QTY) if str(f.get("stock") or "").strip() else 0
        barcode = barcodes.clean(f.get("barcode"))
        scent = f.get("scent", "").strip() or None
        sig = f.get("signature", "").strip().lower() or None
        file = request.files.get("photo")
        data = file.read(MAX_PHOTO + 1) if file and file.filename else b""
        error = None
        if method not in ("barcode", "photo", "scent", "manual"):
            error = "Choose how this product is recognised."
        elif not name or price is None:
            error = "Product name and a valid price are required."
        elif stock is None:
            error = f"Enter how many you have, from 0 to {MAX_QTY:,}."
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
        elif barcode and (dup := product_by_barcode(barcode)):
            error = f"Barcode {barcode} already belongs to {dup.name}. Add stock to it instead."
        elif dup := product_by_name(name):
            error = f"{dup.name} is already registered. Add stock to it in the list below instead."
        elif sig and method in ("photo", "scent"):
            near = _best_matches(sig, 1)
            if near and near[0][0] < DUPLICATE_SCORE:
                error = f"This looks like {near[0][1].name}, which is already registered. Add stock to it instead."
        if error:
            flash(error, "error")
        else:
            p = Product(tenant_id=tid(), name=name, price=price, stock=0, method=method,
                        barcode=barcode, scent=scent, sku=f.get("sku", "").strip()[:60] or None,
                        photo=data or None, photo_mime=_sniff(data) if data else None,
                        signature=sig, reorder_level=integer(f.get("reorder_level"), 5, MAX_QTY),
                        category=tidy_name(f.get("category"))[:60] or None)
            db.session.add(p)
            if stock:
                add_stock(p, stock, "new")
            try:
                db.session.commit()
                flash(f"{name} added.", "ok")
            except Exception:
                db.session.rollback()
                flash("That barcode is already registered.", "error")
        return redirect(url_for("ws.products", tab=method if method in ("photo", "scent", "manual") else None))
    items = Product.query.filter_by(tenant_id=tid()).order_by(Product.name).all()
    history = (StockMovement.query.filter_by(tenant_id=tid())
               .order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(15).all())
    unlinked = [p for p in items if not p.barcode]
    categories = sorted({p.category for p in items if p.category}, key=str.lower)
    return render_template("ws/products.html", items=items, history=history, max_qty=MAX_QTY,
                           duplicates=duplicate_groups(), unlinked=unlinked, undo_window=UNDO_WINDOW,
                           categories=categories)


@ws_bp.post("/products/<int:pid>/edit")
@tenant_admin
def product_edit(pid):
    """Change a product's name, price, category, SKU or reorder level."""
    p = Product.query.filter_by(id=pid, tenant_id=tid()).first_or_404()
    f = request.form
    name, price = tidy_name(f.get("name")), money(f.get("price"))
    if not name or price is None:
        flash("Product name and a valid price are required.", "error")
        return redirect(url_for("ws.products"))
    dup = product_by_name(name)
    if dup and dup.id != p.id:
        flash(f"{dup.name} is already registered. Choose another name.", "error")
        return redirect(url_for("ws.products"))
    p.name, p.price = name, price
    p.category = tidy_name(f.get("category"))[:60] or None
    p.sku = f.get("sku", "").strip()[:60] or None
    p.reorder_level = integer(f.get("reorder_level"), p.reorder_level, MAX_QTY)
    db.session.commit()
    flash(f"{name} updated.", "ok")
    return redirect(url_for("ws.products"))


@ws_bp.post("/products/scan-in")
@tenant_user
def scan_in():
    """Counting stock in by barcode: each scan of a known code adds `quantity` units (default 1).

    A quantity above one suits a carton or a case: scan once and count the whole box.
    A code never creates a second product:
    - it is cleaned and matched however it was read (UPC-A or EAN-13, scanner prefixes, lost zeros);
    - an unknown code can be linked to a product that has no barcode yet (`product_id`), and registering it under
      the name of an existing product links it to that product instead of creating a copy;
    - `scan_id` makes a retried or double-sent scan count once.
    """
    j = request.get_json(silent=True) or {}
    code = barcodes.clean(j.get("barcode"))
    if not code:
        return {"error": "No barcode received."}, 400
    raw_qty = j.get("quantity")
    qty = integer(raw_qty, None, MAX_QTY) if str(raw_qty if raw_qty is not None else "").strip() else 1
    if not qty:
        return {"error": f"Units per scan must be a whole number from 1 to {MAX_QTY:,}."}, 400
    ref = str(j.get("scan_id") or "").strip()[:40] or None
    if ref and (done := StockMovement.query.filter_by(tenant_id=tid(), client_ref=ref).first()):
        return {"found": True, "repeat": True, "added": done.quantity, "movement": done.id,
                "product": _product_json(done.product)}

    def counted(p, source="scan", note=None, **extra):
        m = add_stock(p, qty, source, note, ref=ref)
        db.session.commit()
        return {"found": True, "added": qty, "movement": m.id, "product": _product_json(p), **extra}

    p = product_by_barcode(code, lock=True)
    if p:
        return counted(p)

    # Unknown code: link it to an existing product the cashier picked.
    if j.get("product_id"):
        p = Product.query.filter_by(id=integer(j.get("product_id"), -1), tenant_id=tid()).with_for_update().first()
        if not p:
            return {"error": "That product no longer exists."}, 404
        if p.barcode:
            return {"found": False, "barcode": code,
                    "error": f"{p.name} already has barcode {p.barcode}. Pick another product or register a new one."}, 409
        p.barcode = code
        return counted(p, note=f"Barcode {code} linked", linked=True)

    name, price = tidy_name(j.get("name")), money(j.get("price"))
    if not name and j.get("name") is None and j.get("price") is None:
        return {"found": False, "barcode": code}
    if not name:
        return {"found": False, "barcode": code, "error": "Enter the product name."}
    existing = product_by_name(name)
    if existing:
        if existing.barcode:
            return {"found": False, "barcode": code,
                    "error": f"{existing.name} already has barcode {existing.barcode}. If this is a different "
                             "product, give it a different name, for example with its size."}, 409
        existing.barcode = code
        return counted(existing, note=f"Barcode {code} linked", linked=True)
    if price is None:
        return {"found": False, "barcode": code, "error": "Enter a valid price for the new product."}
    p = Product(tenant_id=tid(), name=name, price=price, stock=0, method="barcode", barcode=code, reorder_level=5)
    db.session.add(p)
    try:
        db.session.flush()
    except Exception:  # lost a race with another scanner registering the same code
        db.session.rollback()
        p = product_by_barcode(code, lock=True)
        if not p:
            return {"error": "Could not register that barcode. Try again."}, 409
        return counted(p)
    return counted(p, "new", "Registered by scan", created=True)


UNDO_WINDOW = timedelta(hours=24)


@ws_bp.post("/stock/<int:mid>/undo")
@tenant_user
def undo_stock(mid):
    """Take back a stock addition made by mistake (a double scan, a wrong quantity)."""
    m = StockMovement.query.filter_by(id=mid, tenant_id=tid()).first()
    wants_json = request.is_json or request.accept_mimetypes.best == "application/json"

    def reply(msg, ok, status=200):
        if wants_json:
            return ({"ok": ok, "message": msg, "stock": m.product.stock if (m and ok) else None}, status)
        flash(msg, "ok" if ok else "error")
        return redirect(url_for("ws.products"))

    if not m:
        return reply("That stock entry was already undone.", False, 404)
    if current_user.role != "admin" and m.created_by != current_user.id:
        return reply("Only the person who added it, or an admin, can undo this.", False, 403)
    if utcnow() - m.created_at > UNDO_WINDOW:
        return reply("Stock added more than a day ago cannot be undone. Use a sale or adjust by hand.", False, 409)
    p = Product.query.filter_by(id=m.product_id, tenant_id=tid()).with_for_update().first()
    if p.stock < m.quantity:
        return reply(f"Only {p.stock} of {p.name} are left, so {m.quantity} cannot be taken back.", False, 409)
    p.stock -= m.quantity
    name, qty = p.name, m.quantity
    db.session.delete(m)
    db.session.commit()
    m = None
    if wants_json:
        return {"ok": True, "message": f"Took back {qty} of {name}.", "stock": p.stock}
    flash(f"Took back {qty} of {name}.", "ok")
    return redirect(url_for("ws.products"))


@ws_bp.post("/products/merge")
@tenant_admin
def merge_products():
    """Fold duplicate products into the one to keep: stock, sales, stock history, barcode and photo move over.

    The form sends `keep` and every product id in the group as `ids`; all but `keep` are merged into it.
    """
    keep_id = integer(request.form.get("keep"), -1)
    ids = {i for i in (integer(x, -1) for x in request.form.getlist("ids")) if i > 0} - {keep_id}
    keep = Product.query.filter_by(id=keep_id, tenant_id=tid()).with_for_update().first()
    drops = Product.query.filter(Product.tenant_id == tid(), Product.id.in_(ids)).with_for_update().all() if ids else []
    if not keep or not drops:
        flash("Choose which product to keep and at least one to merge into it.", "error")
        return redirect(url_for("ws.products"))
    codes = {barcodes.key(p.barcode) for p in [keep, *drops] if p.barcode}
    if len(codes) > 1:
        flash("These products have different barcodes, so they are different products. Rename one instead.", "error")
        return redirect(url_for("ws.products"))
    moved_barcode = None if keep.barcode else next((p.barcode for p in drops if p.barcode), None)
    for drop in drops:
        keep.stock += drop.stock
        Sale.query.filter_by(tenant_id=tid(), product_id=drop.id).update({"product_id": keep.id})
        StockMovement.query.filter_by(tenant_id=tid(), product_id=drop.id).update({"product_id": keep.id})
        db.session.expire(drop, ["movements"])  # they belong to `keep` now; do not cascade-delete them
        for attr in ("sku", "scent", "photo", "photo_mime", "signature"):
            if not getattr(keep, attr) and getattr(drop, attr):
                setattr(keep, attr, getattr(drop, attr))
        db.session.delete(drop)
    db.session.flush()  # free the barcode before giving it to the product we keep
    if moved_barcode:
        keep.barcode = moved_barcode
    db.session.commit()
    ensure_barcode_index()
    n = len(drops)
    flash(f"Merged {n} duplicate{'s' if n != 1 else ''} into {keep.name}. It now has {keep.stock} in stock.", "ok")
    return redirect(url_for("ws.products"))


def ensure_barcode_index():
    """Create the one-barcode-per-product rule if older duplicate data stopped it being created at start-up."""
    try:
        with db.engine.begin() as conn:
            conn.execute(db.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_product_barcode ON products (tenant_id, barcode)"))
    except Exception:  # duplicates still exist; the Stock page lists them for merging
        pass


# ------------------------------------------------------------ bulk import

IMPORT_MAX_ROWS = 2000
IMPORT_MAX_BYTES = 1024 * 1024
IMPORT_COLUMNS = ("name", "price", "quantity", "barcode", "sku", "reorder_level", "category")
HEADER_ALIASES = {
    "name": "name", "product": "name", "product name": "name", "item": "name", "description": "name",
    "price": "price", "selling price": "price", "unit price": "price",
    "quantity": "quantity", "qty": "quantity", "stock": "quantity", "units": "quantity", "count": "quantity",
    "barcode": "barcode", "ean": "barcode", "upc": "barcode", "code": "barcode",
    "sku": "sku", "reorder level": "reorder_level", "reorder_level": "reorder_level", "reorder": "reorder_level",
    "category": "category", "department": "category", "group": "category", "type": "category",
}
IMPORT_TEMPLATE = ("name,price,quantity,barcode,sku,reorder_level,category\n"
                   "Bath soap 250g,1.50,24,6001234567890,SOAP-250,6,Toiletries\n"
                   "Cooking oil 2L,4.20,12,,OIL-2L,4,Groceries\n")


def _read_import_rows(text):
    """Parse CSV text (comma, semicolon or tab separated, header row optional) into dicts keyed by IMPORT_COLUMNS.

    Returns (rows, error). Each row carries its line number for error messages.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], "The list is empty."
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO("\n".join(lines)), dialect)
    first = next(reader)
    mapped = [HEADER_ALIASES.get(c.strip().lower().replace("_", " "), HEADER_ALIASES.get(c.strip().lower()))
              for c in first]
    if "name" in mapped or "barcode" in mapped or "sku" in mapped:
        columns, data, start = mapped, list(reader), 2
    else:  # no header row: name, price, quantity, barcode, sku, reorder_level
        columns, data, start = list(IMPORT_COLUMNS), [first, *reader], 1
    if len(data) > IMPORT_MAX_ROWS:
        return [], f"Import at most {IMPORT_MAX_ROWS:,} rows at a time."
    rows = []
    for n, values in enumerate(data, start):
        row = {"line": n}
        for col, val in zip(columns, values):
            if col and not row.get(col):
                row[col] = val.strip()
        rows.append(row)
    return rows, None


def import_stock(rows, update_prices=False):
    """Apply parsed rows: restock products that exist, create the ones that do not.

    A row matches an existing product by barcode, then SKU, then exact name (ignoring case).
    Returns a summary dict and a list of per-line problems; good rows are applied even if others fail.
    """
    products = Product.query.filter_by(tenant_id=tid()).all()
    by_barcode = {barcodes.key(p.barcode): p for p in products if p.barcode}
    by_sku = {p.sku.lower(): p for p in products if p.sku}
    by_name = {tidy_name(p.name).lower(): p for p in products}
    summary = {"created": 0, "restocked": 0, "units": 0}
    problems = []
    for r in rows:
        line, name = r["line"], tidy_name(r.get("name"))
        barcode, sku = barcodes.clean(r.get("barcode")), (r.get("sku") or "")[:60] or None
        bkey = barcodes.key(barcode)
        qty = integer(r.get("quantity"), None, MAX_QTY) if r.get("quantity") else 0
        price = money(r.get("price")) if r.get("price") else None
        if qty is None:
            problems.append(f"Line {line}: quantity must be a whole number from 0 to {MAX_QTY:,}.")
            continue
        if r.get("price") and price is None:
            problems.append(f"Line {line}: price {r['price']!r} is not a valid amount.")
            continue
        p = (by_barcode.get(bkey) if barcode else None) or (by_sku.get(sku.lower()) if sku else None) \
            or (by_name.get(name.lower()) if name else None)
        if p:
            if barcode and p.barcode and barcodes.key(p.barcode) != bkey:
                problems.append(f"Line {line}: {p.name} already has barcode {p.barcode}, not {barcode}.")
                continue
            if barcode and not p.barcode and bkey not in by_barcode:
                p.barcode = barcode
                by_barcode[bkey] = p
            if update_prices and price is not None:
                p.price = price
            if r.get("category") and not p.category:
                p.category = tidy_name(r["category"])[:60]
            if qty:
                add_stock(p, qty, "import")
                summary["restocked"] += 1
                summary["units"] += qty
            continue
        if not name or price is None:
            problems.append(f"Line {line}: new products need a name and a price.")
            continue
        p = Product(tenant_id=tid(), name=name, price=price, stock=0, barcode=barcode, sku=sku,
                    method="barcode" if barcode else "manual",
                    reorder_level=integer(r.get("reorder_level"), 5, MAX_QTY),
                    category=tidy_name(r.get("category"))[:60] or None)
        db.session.add(p)
        if qty:
            add_stock(p, qty, "new", "Imported")
        summary["created"] += 1
        summary["units"] += qty
        by_name[name.lower()] = p
        if barcode:
            by_barcode[bkey] = p
        if sku:
            by_sku[sku.lower()] = p
    return summary, problems


@ws_bp.post("/products/import")
@tenant_user
def products_import():
    """Add stock in bulk from an uploaded CSV file or a pasted list (a delivery note, a stock count)."""
    file = request.files.get("file")
    if file and file.filename:
        raw = file.read(IMPORT_MAX_BYTES + 1)
        if len(raw) > IMPORT_MAX_BYTES:
            flash("The file must be 1 MB or smaller.", "error")
            return redirect(url_for("ws.products", tab="import"))
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        text = request.form.get("rows", "")[:IMPORT_MAX_BYTES]
    rows, error = _read_import_rows(text)
    if error:
        flash(error, "error")
        return redirect(url_for("ws.products", tab="import"))
    summary, problems = import_stock(rows, update_prices=bool(request.form.get("update_prices")))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Nothing was imported: two rows use the same barcode. Check the file and try again.", "error")
        return redirect(url_for("ws.products", tab="import"))
    done = summary["created"] + summary["restocked"]
    if done:
        flash(f"Imported {done} row{'s' if done != 1 else ''}: {summary['created']} new, "
              f"{summary['restocked']} restocked, {summary['units']:,} units added.", "ok")
    for msg in problems[:5]:
        flash(msg, "error")
    if len(problems) > 5:
        flash(f"…and {len(problems) - 5} more rows were skipped.", "error")
    if not done and not problems:
        flash("No rows had stock to add.", "error")
    return redirect(url_for("ws.products", tab="import"))


@ws_bp.get("/products/import-template.csv")
@tenant_user
def import_template():
    return Response(IMPORT_TEMPLATE, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=stock-import-template.csv"})


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
    code = barcodes.clean(j.get("barcode"))
    if code:
        p = product_by_barcode(code)
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
    sale, error, warning = complete_sale(p, qty, client, j.get("paid"), j.get("method"), j.get("phone"),
                                         j.get("payment_ref"))
    if error:
        db.session.rollback()
        return {"error": error}, 400
    return {"ok": True, "total": str(sale.total), "stock": p.stock, "name": p.name, "warning": warning,
            "receipt": url_for("ws.receipt", sid=sale.id, print=1, back="quick")}


@ws_bp.post("/products/<int:pid>/restock")
@tenant_user
def restock(pid):
    p = Product.query.filter_by(id=pid, tenant_id=tid()).with_for_update().first_or_404()
    qty = integer(request.form.get("qty"), None, MAX_QTY)
    if not qty:
        flash(f"Enter a quantity from 1 to {MAX_QTY:,}.", "error")
    else:
        add_stock(p, qty, "restock", request.form.get("note", "").strip())
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
        p = Product.query.filter_by(id=integer(f.get("product_id"), -1), tenant_id=tid()).with_for_update().first()
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
            sale, error, warning = complete_sale(p, qty, client, f.get("paid"), f.get("method"), f.get("phone"),
                                                 f.get("payment_ref"))
            if error:
                db.session.rollback()
                flash(error, "error")
                return redirect(url_for("ws.sales"))
            if warning:
                flash(warning, "error")
                return redirect(url_for("ws.sales"))
            return redirect(url_for("ws.receipt", sid=sale.id, print=1, back="sales"))
        return redirect(url_for("ws.sales"))

    kind = request.args.get("type", "all")
    query = Sale.query.filter_by(tenant_id=tid())
    # Pending and refunded mobile-money sales are not debts, so they never count as credit.
    owing = db.and_(Sale.paid < Sale.total_sql(),
                    db.or_(Sale.payment_status.is_(None), Sale.payment_status.notin_(("pending", "refunded"))))
    if kind == "cash":
        query = query.filter(db.not_(owing))
    elif kind == "credit":
        query = query.filter(owing)
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
    counts = {"all": base.count(), "credit": base.filter(owing).count()}
    counts["cash"] = counts["all"] - counts["credit"]
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
    if s.order_id:  # rung up on the Register: one receipt for the whole order
        return redirect(url_for("ws.order_receipt", oid=s.order_id, print=request.args.get("print"),
                                back=request.args.get("back", "sales")))
    number = Sale.query.filter(Sale.tenant_id == tid(), Sale.id <= s.id).count()
    cashier = db.session.get(User, s.created_by) if s.created_by else None
    return render_template("ws/receipt.html", s=s, number=number, tenant=current_user.tenant,
                           cashier=cashier, autoprint=bool(request.args.get("print")),
                           back=request.args.get("back", "sales"))


@ws_bp.post("/sales/<int:sid>/check-payment")
@tenant_user
def check_payment(sid):
    """Ask EcoCash what happened to a charge we could not confirm."""
    s = Sale.query.filter_by(id=sid, tenant_id=tid(), payment_method="ecocash", payment_status="pending").first_or_404()
    if s.order_id:
        from .pos import order_check
        return order_check(s.order_id)
    try:
        res = ecocash().lookup(s.payment_phone, s.payment_correlator)
    except EcoCashUnknown:
        flash("EcoCash did not answer. Try again in a moment.", "error")
    except EcoCashError as e:
        if e.http_status not in (400, 404):
            flash(f"Could not check the payment: {e}", "error")
            return redirect(url_for("ws.sales"))
        # Failed charges are not stored by EcoCash, so "not found" means the customer was not charged.
        p = Product.query.filter_by(id=s.product_id, tenant_id=tid()).with_for_update().first()
        if p:
            p.stock += s.quantity
        db.session.delete(s)
        db.session.commit()
        flash("EcoCash has no payment for that sale. The sale was cancelled and the stock returned.", "ok")
    else:
        if res.ok:
            s.paid, s.payment_status, s.payment_ref = s.total if s.paid < s.total else s.paid, "paid", res.ecocash_reference
            db.session.commit()
            flash("EcoCash confirmed the payment.", "ok")
        else:
            flash(f"EcoCash reports the payment as {res.status or 'not complete'}.", "error")
    return redirect(url_for("ws.sales"))


@ws_bp.post("/sales/<int:sid>/refund")
@tenant_admin
def refund(sid):
    """Refund an EcoCash payment to the customer's wallet and put the stock back."""
    s = Sale.query.filter_by(id=sid, tenant_id=tid(), payment_method="ecocash", payment_status="paid").first_or_404()
    if s.order_id:
        from .pos import order_refund
        return order_refund(s.order_id)
    amount = s.paid
    try:
        res = ecocash().refund(s.payment_phone, amount, s.payment_ref, tid(), s.id,
                               reverse=request.form.get("kind") == "reverse")
    except EcoCashError as e:
        flash(f"Refund failed: {e}", "error")
    except EcoCashUnknown:
        flash("EcoCash did not answer. Do not retry blindly: check the customer's wallet, then try again.", "error")
    else:
        if res.ok:
            s.paid, s.payment_status = 0, "refunded"
            p = Product.query.filter_by(id=s.product_id, tenant_id=tid()).with_for_update().first()
            if p:
                p.stock += s.quantity
            db.session.commit()
            flash(f"Refunded {amount} to {s.payment_phone}.", "ok")
        else:
            flash("EcoCash did not complete the refund.", "error")
    return redirect(url_for("ws.sales"))


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
    if s.settled or s.balance <= 0:
        flash("Nothing is owed on that sale.", "error")
    elif not amt or amt > s.balance:
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

DEFAULT_COLOURS = {"accent": "#0f5c4a", "background": "#eef1ef", "panel": "#ffffff"}


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
            if request.form.get("reset_colours") or val.lower() == DEFAULT_COLOURS[field]:
                val = ""  # untouched defaults stay unset so light/dark mode keeps working
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


# ------------------------------------------------------------ payment settings

@ws_bp.route("/payments", methods=["GET", "POST"])
@tenant_admin
def payments():
    t = current_user.tenant
    tp = t.payment
    if request.method == "POST":
        f = request.form
        tp = tp or TenantPayment(tenant_id=t.id)
        db.session.add(tp)
        key = current_app.extensions["settings"].secret_key
        tp.username = f.get("username", "").strip()[:120] or None
        tp.merchant_code = f.get("merchant_code", "").strip()[:40] or None
        tp.merchant_number = normalise_msisdn(f.get("merchant_number")) or None
        tp.merchant_name = f.get("merchant_name", "").strip()[:120] or None
        tp.terminal_id = f.get("terminal_id", "").strip()[:40] or None
        tp.location = f.get("location", "").strip()[:60] or None
        # Secrets are never shown again; blank means keep the saved value.
        if f.get("password"):
            tp.password_enc = encrypt(f["password"], key)
        if f.get("merchant_pin"):
            tp.merchant_pin_enc = encrypt(f["merchant_pin"], key)
        if tp.merchant_number and not ECOCASH_RE.match(tp.merchant_number):
            db.session.rollback()
            flash("Merchant number must be an EcoCash number, for example 0771234567.", "error")
            return redirect(url_for("ws.payments"))
        tp.ecocash_enabled = bool(f.get("ecocash_enabled"))
        if tp.ecocash_enabled and not tp.complete:
            tp.ecocash_enabled = False
            flash("Saved, but EcoCash stays off until username, password, merchant code and merchant number are filled in.", "error")
        else:
            flash("Payment settings saved.", "ok")
        db.session.commit()
        return redirect(url_for("ws.payments"))
    return render_template("ws/payments.html", tp=tp)
