"""The Register (a cart-based point of sale), its receipts, the day report, Business settings and languages.

The Register sends one checkout with several lines. The server prices everything again from the database, so
what the browser shows is a preview and never the authority: discounts, sales tax (included in shelf prices or
added on top), the second currency and the change are all worked out here.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from . import db
from .i18n import COOKIE, js_catalog, translate
from .models import METHOD_LABELS, Client, Order, Product, Sale, User, utcnow
from .payments import ECOCASH_RE, EcoCashError, EcoCashUnknown, new_correlator, normalise_msisdn
from .regional import (
    COUNTRIES,
    CURRENCIES,
    LANGUAGES,
    currency_label,
    fmt_money,
    js_config,
    local_now,
    precision,
    quantize,
    timezones,
    to_local,
    valid_currency,
    valid_locale,
    valid_timezone,
)
from .workspace import MAX_QTY, ecocash, integer, money, tenant_admin, tenant_user, tid, ws_bp

misc_bp = Blueprint("misc", __name__)

POS_METHODS = ("cash", "card", "mobile", "bank", "ecocash", "credit")
MOBILE_PROVIDERS = ["OneMoney", "InnBucks", "O'mari", "M-Pesa", "MTN MoMo", "Airtel Money", "Orange Money", "Wave",
                    "Tigo Pesa", "Vodacom M-Pesa", "Telebirr", "Mukuru", "Other"]
MAX_LINES = 200
HUNDRED = Decimal(100)

# Strings the Register's script shows; sent translated with the page.
JS_STRINGS = [
    "Added", "Cart is empty", "Charge", "Change", "Change due", "Checkout failed", "Choose a customer for credit or part payment",
    "Clear the cart?", "Exact", "Held carts", "Item", "Items", "No products match", "Not enough cash", "Nothing held",
    "Only {n} in stock", "Out of stock", "Paid", "Print receipt", "Receipt", "Remove", "Resume", "Sale complete",
    "Saved for later", "Scan or search", "Short by", "Still owed", "Subtotal", "Total", "Discount", "Walk-in customer",
    "{n} in stock", "No connection. Check the network and try again.", "Unknown barcode", "Customer", "Cart",
    "New sale", "Enter the transaction code", "Enter the customer's EcoCash number", "Waiting for the customer to approve…",
    "All", "includes", "Tax", "Pay in", "Amount", "Hold", "Enter the cash received",
]


def _dec(v, default=None):
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, AttributeError, ValueError):
        return default
    return d if d.is_finite() else default


# ------------------------------------------------------------------ pricing

def price_order(tenant, lines, order_discount=None):
    """Work out every amount for a checkout.

    `lines` is a list of (product, quantity, line discount %). `order_discount` is ("pct", value) or ("amt", value).
    Returns (line results, totals). Each line result has gross, discount, tax and total; totals has subtotal,
    discount, tax and total. All amounts are rounded to the currency's decimals; an order discount is shared over
    the lines in proportion to their value, and the last line takes any rounding remainder so the sum is exact.
    """
    cur = tenant.currency_code
    q = lambda x: quantize(x, cur)  # noqa: E731
    rate, inclusive = tenant.tax_percent, tenant.tax_is_inclusive
    out = []
    for p, qty, pct in lines:
        gross = q(p.price * qty)
        ldisc = q(gross * pct / HUNDRED) if pct else Decimal(0)
        out.append({"product": p, "qty": qty, "gross": gross, "ldisc": ldisc, "after": gross - ldisc})
    base = sum((x["after"] for x in out), Decimal(0))
    od = Decimal(0)
    if order_discount and base > 0:
        kind, val = order_discount
        od = q(base * min(val, HUNDRED) / HUNDRED) if kind == "pct" else min(q(val), base)
    left = od
    for i, x in enumerate(out):
        share = left if i == len(out) - 1 else (q(od * x["after"] / base) if base else Decimal(0))
        share = min(share, x["after"], left)
        left -= share
        net = x["after"] - share
        if rate > 0:
            tax = q(net * rate / (HUNDRED + rate)) if inclusive else q(net * rate / HUNDRED)
        else:
            tax = Decimal(0)
        x.update(discount=x["ldisc"] + share, tax=tax, total=net if inclusive else net + tax)
    totals = {k: sum((x[s] for x in out), Decimal(0))
              for k, s in (("subtotal", "gross"), ("discount", "discount"), ("tax", "tax"), ("total", "total"))}
    return out, totals


def allocate(amount, parts):
    """Share a payment over lines in order, filling each before the next."""
    shares = []
    for p in parts:
        take = min(amount, p)
        shares.append(take)
        amount -= take
    return shares


def order_number(o):
    return Order.query.filter(Order.tenant_id == o.tenant_id, Order.id <= o.id).count()


# ------------------------------------------------------------------ register

def _product_card(p):
    return {"id": p.id, "name": p.name, "price": str(p.price), "stock": p.stock, "barcode": p.barcode or "",
            "sku": p.sku or "", "category": p.category or "",
            "photo": url_for("ws.product_photo", pid=p.id) if p.photo else None}


@ws_bp.get("/register")
@tenant_user
def register():
    t = current_user.tenant
    items = Product.query.filter_by(tenant_id=tid()).order_by(Product.name).all()
    categories = sorted({p.category for p in items if p.category}, key=str.lower)
    clients = Client.query.filter_by(tenant_id=tid()).order_by(Client.name).all()
    return render_template(
        "ws/register.html", tenant=t, cfg=js_config(t), categories=categories,
        products=[_product_card(p) for p in items],
        clients=[{"id": c.id, "name": c.name, "phone": c.phone or ""} for c in clients],
        ecocash_on=bool(t.payment and t.payment.ecocash_enabled), providers=MOBILE_PROVIDERS,
        strings=js_catalog(JS_STRINGS))


def _fail(message, status=400, **extra):
    db.session.rollback()
    return jsonify({"ok": False, "error": message, **extra}), status


def _order_reply(o, warning=None):
    cur, loc = o.currency, current_user.tenant.number_locale
    stock = {}
    for s in o.lines:
        p = db.session.get(Product, s.product_id) if s.product_id else None
        if p:
            stock[p.id] = p.stock
    return jsonify({
        "ok": True, "order": o.id, "number": order_number(o), "warning": warning,
        "total": str(o.total), "total_fmt": fmt_money(o.total, cur, loc), "paid_fmt": fmt_money(o.paid, cur, loc),
        "balance_fmt": fmt_money(o.balance, cur, loc) if o.balance > 0 else None,
        "change_fmt": fmt_money(o.change or 0, o.tender_currency or cur, loc) if o.change else None,
        "stock": stock, "receipt": url_for("ws.order_receipt", oid=o.id, print=1, back="register"),
    })


@ws_bp.post("/register/checkout")
@tenant_user
def checkout():
    t = current_user.tenant
    j = request.get_json(silent=True) or {}
    ref = str(j.get("ref") or "").strip()[:40] or None
    if ref and (done := Order.query.filter_by(tenant_id=tid(), client_ref=ref).first()):
        return _order_reply(done)

    raw_lines = j.get("items") or []
    if not isinstance(raw_lines, list) or not raw_lines:
        return _fail(translate("Cart is empty"))
    if len(raw_lines) > MAX_LINES:
        return _fail(translate("A sale can have at most {n} lines.", n=MAX_LINES))

    wanted = []
    for row in raw_lines:
        if not isinstance(row, dict):
            return _fail(translate("Something in the cart was not right. Clear it and try again."))
        pid, qty = integer(row.get("product_id"), -1), integer(row.get("quantity"), None, MAX_QTY)
        pct = _dec(row.get("discount_pct") or 0, None)
        if not qty:
            return _fail(translate("Every line needs a quantity of at least 1."))
        if pct is None or pct < 0 or pct > 100:
            return _fail(translate("Line discounts must be between 0 and 100%."))
        wanted.append((pid, qty, pct))

    ids = {pid for pid, _, _ in wanted}
    products = {p.id: p for p in Product.query.filter(Product.tenant_id == tid(), Product.id.in_(ids)).with_for_update()}
    need = defaultdict(int)
    for pid, qty, _ in wanted:
        if pid not in products:
            return _fail(translate("A product in the cart was removed. Refresh the Register."), 409)
        need[pid] += qty
    for pid, qty in need.items():
        p = products[pid]
        if qty > p.stock:
            return _fail(translate("Only {n} of {name} left in stock.", n=p.stock, name=p.name), 409, product=pid, stock=p.stock)

    od = None
    disc = j.get("discount") or {}
    if isinstance(disc, dict) and disc.get("value") not in (None, "", 0, "0"):
        val = _dec(disc.get("value"))
        if val is None or val < 0:
            return _fail(translate("Enter a valid discount."))
        od = ("pct" if disc.get("type") == "pct" else "amt", val)
        if od[0] == "pct" and val > 100:
            return _fail(translate("A discount cannot be more than 100%."))

    lines, totals = price_order(t, [(products[pid], qty, pct) for pid, qty, pct in wanted], od)
    total = totals["total"]

    client = None
    if j.get("client_id"):
        client = Client.query.filter_by(id=integer(j.get("client_id"), -1), tenant_id=tid()).first()
        if not client:
            return _fail(translate("That customer no longer exists."))

    method = j.get("method") if j.get("method") in POS_METHODS else "cash"
    phone = normalise_msisdn(j.get("phone"))
    pref = str(j.get("payment_ref") or "").strip()[:60] or None
    provider = str(j.get("provider") or "").strip()[:30] or None
    tender_cur, rate, tendered, change = None, None, None, None

    if method == "credit":
        paid = money(j.get("paid"), Decimal(0)) if str(j.get("paid") or "").strip() else Decimal(0)
    elif str(j.get("paid") or "").strip():
        paid = money(j.get("paid"))
        if paid is None:
            return _fail(translate("Enter a valid amount paid."))
    else:
        paid = total
    paid = min(paid, total)

    if method == "cash" and str(j.get("tendered") or "").strip():
        tendered = _dec(j.get("tendered"))
        if tendered is None or tendered < 0:
            return _fail(translate("Enter the cash received."))
        if j.get("tender_currency") and j.get("tender_currency") == t.alt_currency and t.alt_rate:
            tender_cur, rate = t.alt_currency, Decimal(t.alt_rate)
            tendered = quantize(tendered, tender_cur)
            due_alt = quantize(total * rate, tender_cur)
            if tendered >= due_alt:
                paid, change = total, tendered - due_alt
            else:
                paid = min(total, quantize(tendered / rate, t.currency_code))
        else:
            tender_cur, tendered = t.currency_code, quantize(tendered, t.currency_code)
            if tendered >= total:
                paid, change = total, tendered - total
            else:
                paid = tendered
    if paid < total and not client:
        return _fail(translate("Choose a customer for credit or part payment"))
    if method == "mobile" and not pref:
        return _fail(translate("Enter the transaction code"))
    if method == "ecocash":
        gateway = ecocash()
        if not gateway.enabled:
            return _fail(translate("EcoCash is not set up for this business yet."))
        if not ECOCASH_RE.match(phone):
            return _fail(translate("Enter the customer's EcoCash number"))
        if paid <= 0:
            return _fail(translate("Enter an amount above zero to charge."))

    o = Order(tenant_id=tid(), client=client, currency=t.currency_code, subtotal=totals["subtotal"],
              discount=totals["discount"], tax=totals["tax"], tax_inclusive=t.tax_is_inclusive,
              tax_rate=t.tax_percent if t.tax_percent else None, tax_name=t.tax_label, total=total,
              paid=paid if method != "ecocash" else Decimal(0), payment_method=method, payment_provider=provider,
              payment_phone=phone or None, payment_ref=pref, tender_currency=tender_cur, rate=rate,
              tendered=tendered, change=change, note=str(j.get("note") or "").strip()[:200] or None,
              created_by=current_user.id, client_ref=ref)
    db.session.add(o)
    shares = allocate(paid, [x["total"] for x in lines])
    for x, share in zip(lines, shares):
        p = x["product"]
        p.stock -= x["qty"]
        db.session.add(Sale(tenant_id=tid(), client=client, product_id=p.id, product_name=p.name, quantity=x["qty"],
                            unit_price=p.price, paid=share if method != "ecocash" else 0, created_by=current_user.id,
                            payment_method=method, payment_ref=pref, payment_phone=phone or None, order=o,
                            discount=x["discount"] or None, tax=x["tax"] or None, line_total=x["total"]))
    try:
        db.session.flush()
    except Exception:  # two taps of Charge raced each other with the same ref
        db.session.rollback()
        if ref and (done := Order.query.filter_by(tenant_id=tid(), client_ref=ref).first()):
            return _order_reply(done)
        return _fail(translate("Could not save the sale. Try again."), 409)

    if method != "ecocash":
        db.session.commit()
        return _order_reply(o)

    # EcoCash: keep the order as pending first, so a crash or timeout never loses track of a charge.
    o.payment_status, o.payment_correlator = "pending", new_correlator(tid(), o.id)
    for s in o.lines:
        s.payment_status = "pending"
        s.payment_correlator = o.payment_correlator
    db.session.commit()
    try:
        res = gateway.charge(phone, paid, o.payment_correlator, f"ORDER-{tid()}-{o.id}", f"{o.items} items")
    except EcoCashError as e:
        _cancel_order(o)
        return _fail(translate("EcoCash payment failed: {reason}", reason=e))
    except EcoCashUnknown:
        return _order_reply(o, warning=translate(
            "EcoCash did not answer, so the payment is unconfirmed. Use Check payment on the Sales page before "
            "handing over the goods."))
    if not res.ok:
        _cancel_order(o)
        return _fail(translate("EcoCash did not take the payment."))
    _mark_paid(o, paid, res.ecocash_reference)
    db.session.commit()
    return _order_reply(o)


def _mark_paid(o, paid, reference):
    o.paid, o.payment_status, o.payment_ref = paid, "paid", reference
    for s, share in zip(o.lines, allocate(paid, [s.total for s in o.lines])):
        s.paid, s.payment_status, s.payment_ref = share, "paid", reference


def _cancel_order(o):
    """Put the stock back and remove an order whose payment never happened."""
    for s in list(o.lines):
        p = Product.query.filter_by(id=s.product_id, tenant_id=o.tenant_id).with_for_update().first() if s.product_id else None
        if p:
            p.stock += s.quantity
        db.session.delete(s)
    db.session.delete(o)
    db.session.commit()


def check_order_payment(o):
    """Ask EcoCash what happened to an order's charge we could not confirm. Returns (message, ok)."""
    try:
        res = ecocash().lookup(o.payment_phone, o.payment_correlator)
    except EcoCashUnknown:
        return translate("EcoCash did not answer. Try again in a moment."), False
    except EcoCashError as e:
        if e.http_status not in (400, 404):
            return translate("Could not check the payment: {reason}", reason=e), False
        _cancel_order(o)
        return translate("EcoCash has no payment for that sale. The sale was cancelled and the stock returned."), True
    if res.ok:
        _mark_paid(o, o.total, res.ecocash_reference)
        db.session.commit()
        return translate("EcoCash confirmed the payment."), True
    return translate("EcoCash reports the payment as {status}.", status=res.status or "not complete"), False


def refund_order(o, reverse=False):
    amount = o.paid
    try:
        res = ecocash().refund(o.payment_phone, amount, o.payment_ref, tid(), o.id, reverse=reverse)
    except EcoCashError as e:
        return translate("Refund failed: {reason}", reason=e), False
    except EcoCashUnknown:
        return translate("EcoCash did not answer. Do not retry blindly: check the customer's wallet, then try again."), False
    if not res.ok:
        return translate("EcoCash did not complete the refund."), False
    o.paid, o.payment_status = 0, "refunded"
    for s in o.lines:
        s.paid, s.payment_status = 0, "refunded"
        p = Product.query.filter_by(id=s.product_id, tenant_id=tid()).with_for_update().first() if s.product_id else None
        if p:
            p.stock += s.quantity
    db.session.commit()
    return translate("Refunded {amount} to {phone}.", amount=fmt_money(amount, o.currency, current_user.tenant.number_locale),
                     phone=o.payment_phone), True


@ws_bp.post("/orders/<int:oid>/check-payment")
@tenant_user
def order_check(oid):
    o = Order.query.filter_by(id=oid, tenant_id=tid(), payment_method="ecocash", payment_status="pending").first_or_404()
    msg, ok = check_order_payment(o)
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("ws.sales"))


@ws_bp.post("/orders/<int:oid>/refund")
@tenant_admin
def order_refund(oid):
    o = Order.query.filter_by(id=oid, tenant_id=tid(), payment_method="ecocash", payment_status="paid").first_or_404()
    msg, ok = refund_order(o, reverse=request.form.get("kind") == "reverse")
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("ws.sales"))


@ws_bp.get("/orders/<int:oid>/receipt")
@tenant_user
def order_receipt(oid):
    o = Order.query.filter_by(id=oid, tenant_id=tid()).first_or_404()
    t = current_user.tenant
    alt_total = None
    if o.tender_currency and o.tender_currency != o.currency and o.rate:
        alt_total = quantize(o.total * o.rate, o.tender_currency)
    elif t.alt_currency and t.alt_rate:
        alt_total = None  # shown live below the total only when the customer paid in it
    return render_template("ws/order_receipt.html", o=o, number=order_number(o), tenant=t, alt_total=alt_total,
                           autoprint=bool(request.args.get("print")), back=request.args.get("back", "register"))


# ------------------------------------------------------------------ day report

def _day_bounds(day, tz):
    """The UTC start and end (naive, as stored) of a calendar day in the business's time zone."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)  # noqa: E731
    return to_utc(start), to_utc(end)


@ws_bp.get("/reports/day")
@tenant_user
def day_report():
    t = current_user.tenant
    today = local_now(t.tz).date()
    try:
        day = datetime.strptime(request.args.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = today
    day = min(day, today)
    start, end = _day_bounds(day, t.tz)
    sales = (Sale.query.filter(Sale.tenant_id == tid(), Sale.created_at >= start, Sale.created_at < end)
             .order_by(Sale.created_at).all())
    live = [s for s in sales if s.payment_status not in ("refunded", "pending")]
    refunded = [s for s in sales if s.payment_status == "refunded"]
    pending = [s for s in sales if s.payment_status == "pending"]
    by_method, by_cashier, by_product = defaultdict(Decimal), defaultdict(lambda: [0, Decimal(0)]), defaultdict(lambda: [0, Decimal(0)])
    for s in live:
        by_method[s.payment_method or "cash"] += s.paid
        c = by_cashier[s.created_by]
        c[0] += 1
        c[1] += s.total
        p = by_product[s.product_name]
        p[0] += s.quantity
        p[1] += s.total
    users = {u.id: u.name for u in User.query.filter(User.id.in_([k for k in by_cashier if k])).all()} if by_cashier else {}
    orders = {s.order_id for s in live if s.order_id}
    receipts = len(orders) + sum(1 for s in live if not s.order_id)
    gross = sum((s.total for s in live), Decimal(0))
    summary = {
        "gross": gross, "receipts": receipts, "units": sum(s.quantity for s in live),
        "discount": sum((s.discount or 0 for s in live), Decimal(0)), "tax": sum((s.tax or 0 for s in live), Decimal(0)),
        "received": sum((s.paid for s in live), Decimal(0)), "credit": sum((s.balance for s in live), Decimal(0)),
        "refunds": sum((s.total for s in refunded), Decimal(0)), "refund_count": len(refunded), "pending": len(pending),
        "average": (gross / receipts) if receipts else Decimal(0),
    }
    hours = defaultdict(Decimal)
    for s in live:
        hours[to_local(s.created_at, t.tz).hour] += s.total
    return render_template(
        "ws/day_report.html", tenant=t, day=day, today=today, prev=day - timedelta(days=1),
        next=(day + timedelta(days=1)) if day < today else None, summary=summary,
        methods=sorted(by_method.items(), key=lambda x: -x[1]), labels=METHOD_LABELS,
        cashiers=sorted(((users.get(k, "—"), v[0], v[1]) for k, v in by_cashier.items()), key=lambda x: -x[2]),
        products=sorted(by_product.items(), key=lambda x: -x[1][1])[:12],
        hours=[(h, hours.get(h, Decimal(0))) for h in range(24)], peak=max(hours.values(), default=Decimal(0)),
        generated=utcnow())


# ------------------------------------------------------------------ business settings

@ws_bp.route("/settings", methods=["GET", "POST"])
@tenant_admin
def settings():
    t = current_user.tenant
    if request.method == "POST":
        f = request.form
        country = f.get("country", "").strip().upper()
        currency = f.get("currency", "").strip().upper()
        alt = f.get("alt_currency", "").strip().upper()
        locale = f.get("locale", "").strip()
        tz = f.get("timezone", "").strip()
        lang = f.get("language", "").strip()
        rate = _dec(f.get("tax_rate") or 0)
        alt_rate = _dec(f.get("alt_rate")) if f.get("alt_rate", "").strip() else None
        errors = []
        if country and country not in COUNTRIES:
            errors.append(translate("Choose a country from the list."))
        if not valid_currency(currency):
            errors.append(translate("Choose the currency you sell in."))
        if alt and (not valid_currency(alt) or alt == currency):
            errors.append(translate("The second currency must be a different currency."))
        if alt and (alt_rate is None or alt_rate <= 0):
            errors.append(translate("Enter how many {alt} make 1 {cur}.", alt=alt, cur=currency))
        if not valid_locale(locale):
            errors.append(translate("Choose a number format."))
        if not valid_timezone(tz):
            errors.append(translate("Choose a time zone."))
        if lang and lang not in LANGUAGES:
            errors.append(translate("Choose a language."))
        if rate is None or rate < 0 or rate >= 100:
            errors.append(translate("Tax rate must be a percentage from 0 to 99.99."))
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("ws.settings"))
        t.country, t.currency, t.locale, t.timezone, t.language = country or None, currency, locale, tz, lang or None
        t.alt_currency = alt or None
        t.alt_rate = alt_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if alt else None
        t.tax_name = f.get("tax_name", "").strip()[:20] or None
        t.tax_rate = rate.quantize(Decimal("0.01"))
        t.tax_inclusive = f.get("tax_mode", "inclusive") != "exclusive"
        t.tax_number = f.get("tax_number", "").strip()[:40] or None
        t.phone = f.get("phone", "").strip()[:40] or None
        t.address = f.get("address", "").strip()[:240] or None
        t.receipt_footer = f.get("receipt_footer", "").strip()[:240] or None
        db.session.commit()
        g.lang = current_user.language or t.language or g.get("lang")
        flash(translate("Business settings saved."), "ok")
        return redirect(url_for("ws.settings"))
    from babel import Locale

    locales = sorted({c[3] for c in COUNTRIES.values()} | {t.number_locale})
    locale_names = {}
    for code in locales:
        try:
            locale_names[code] = Locale.parse(code).get_display_name("en")
        except Exception:
            locale_names[code] = code
    currencies = list(dict.fromkeys(CURRENCIES + [t.currency_code] + ([t.alt_currency] if t.alt_currency else [])))
    sample = fmt_money(Decimal("1234567.891"), t.currency_code, t.number_locale)
    return render_template("ws/settings.html", tenant=t, countries=COUNTRIES, currencies=currencies,
                           currency_label=currency_label, locale_names=locale_names, timezones=timezones(),
                           sample=sample, precision=precision)


# ------------------------------------------------------------------ language

def _safe_back(target):
    target = target or ""
    return target if target.startswith("/") and not target.startswith("//") and "\\" not in target else "/"


def _language_reply(user):
    lang = request.form.get("lang", "")
    if lang not in LANGUAGES and lang != "":
        abort(400)
    if user is not None and user.is_authenticated:
        user.language = lang or None
        db.session.commit()
    resp = redirect(_safe_back(request.form.get("next")))
    if lang:
        resp.set_cookie(COOKIE, lang, max_age=365 * 86400, samesite="Lax", secure=request.is_secure, httponly=True)
    else:
        resp.delete_cookie(COOKIE)
    return resp


@misc_bp.post("/language")
def set_language():
    """Sign-in pages and the administrator console: the choice is kept in a cookie (and on the admin's account)."""
    from flask_login import current_user as user

    return _language_reply(user)


@ws_bp.post("/language")
@tenant_user
def workspace_language():
    """A member's own screen language, saved on their account so it follows them to every device."""
    return _language_reply(current_user)
