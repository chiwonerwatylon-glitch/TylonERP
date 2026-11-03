"""The Register, order receipts, day report, Business settings, languages and the installable app."""
from decimal import Decimal

import pytest

from app import db
from app.models import Client, Order, Product, Sale, Tenant
from app.pos import price_order
from app.regional import fmt_money, quantize

from .conftest import login


@pytest.fixture
def shop(app, client, two_tenants):
    a = two_tenants["alpha"]
    with app.app_context():
        db.session.add_all([
            Product(tenant_id=a["tenant"], name="Bread", price=Decimal("1.20"), stock=50, barcode="6001234567890",
                    category="Bakery"),
            Product(tenant_id=a["tenant"], name="Milk 1L", price=Decimal("0.95"), stock=3, category="Dairy"),
        ])
        db.session.commit()
        ids = {p.name: p.id for p in Product.query.filter_by(tenant_id=a["tenant"])}
    login(client, "alpha", a["email"])
    return {**a, "ids": ids}


def set_tenant(app, slug, **fields):
    with app.app_context():
        t = Tenant.query.filter_by(slug=slug).first()
        for k, v in fields.items():
            setattr(t, k, v)
        db.session.commit()


def checkout(client, **body):
    return client.post("/t/alpha/app/register/checkout", json=body)


# ---------------------------------------------------------------- formatting

def test_money_follows_locale_and_currency():
    assert fmt_money(Decimal("1234.5"), "USD", "en_US") == "$1,234.50"
    assert fmt_money(Decimal("1234.5"), "EUR", "pt_PT").replace("\xa0", " ").replace(" ", " ") == "1 234,50 €"
    assert fmt_money(Decimal("1234.5"), "ZWG", "en_ZW").startswith("ZiG")
    assert quantize(Decimal("1234.5"), "UGX") == Decimal("1235")


# ---------------------------------------------------------------- pricing

class _P:
    def __init__(self, price):
        self.price = Decimal(price)


class _T:
    def __init__(self, rate="0", inclusive=True, currency="USD"):
        self.tax_percent, self.tax_is_inclusive, self.currency_code = Decimal(rate), inclusive, currency


def test_inclusive_tax_is_inside_the_total():
    _, tot = price_order(_T("15", True), [(_P("11.50"), 2, Decimal(0))])
    assert tot["total"] == Decimal("23.00")
    assert tot["tax"] == Decimal("3.00")


def test_exclusive_tax_is_added():
    _, tot = price_order(_T("10", False), [(_P("10.00"), 1, Decimal(0))])
    assert tot["total"] == Decimal("11.00")


def test_order_discount_is_shared_exactly():
    lines, tot = price_order(_T(), [(_P("1.00"), 1, Decimal(0)), (_P("1.00"), 1, Decimal(0)), (_P("1.00"), 1, Decimal(0))],
                             ("amt", Decimal("1.00")))
    assert tot["discount"] == Decimal("1.00")
    assert tot["total"] == Decimal("2.00")
    assert sum(x["total"] for x in lines) == tot["total"]


def test_line_and_percentage_discount():
    _, tot = price_order(_T(), [(_P("10.00"), 1, Decimal(10))], ("pct", Decimal(50)))
    assert tot["total"] == Decimal("4.50")


# ---------------------------------------------------------------- checkout

def test_register_page_lists_products(client, shop):
    r = client.get("/t/alpha/app/register")
    assert r.status_code == 200
    assert b"Bread" in r.data and b"Bakery" in r.data


def test_cash_checkout_with_change(app, client, shop):
    r = checkout(client, ref="r1", method="cash", tendered="10",
                 items=[{"product_id": shop["ids"]["Bread"], "quantity": 2}, {"product_id": shop["ids"]["Milk 1L"], "quantity": 1}])
    j = r.get_json()
    assert j["ok"], j
    with app.app_context():
        o = db.session.get(Order, j["order"])
        assert o.total == Decimal("3.35") and o.paid == Decimal("3.35") and o.change == Decimal("6.65")
        assert len(o.lines) == 2 and all(s.balance == 0 for s in o.lines)
        assert db.session.get(Product, shop["ids"]["Milk 1L"]).stock == 2
    assert client.get(f"/t/alpha/app/orders/{j['order']}/receipt").status_code == 200


def test_checkout_is_recorded_once(app, client, shop):
    body = {"ref": "same", "method": "card", "items": [{"product_id": shop["ids"]["Bread"], "quantity": 1}]}
    first, again = checkout(client, **body).get_json(), checkout(client, **body).get_json()
    assert first["order"] == again["order"]
    with app.app_context():
        assert Order.query.count() == 1
        assert db.session.get(Product, shop["ids"]["Bread"]).stock == 49


def test_not_enough_stock(client, shop):
    r = checkout(client, items=[{"product_id": shop["ids"]["Milk 1L"], "quantity": 4}])
    assert r.status_code == 409


def test_short_cash_needs_a_customer(client, shop):
    r = checkout(client, method="cash", tendered="1", items=[{"product_id": shop["ids"]["Bread"], "quantity": 2}])
    assert r.status_code == 400


def test_credit_sale_becomes_a_debt(app, client, shop):
    r = checkout(client, method="credit", client_id=shop["client"], paid="1",
                 items=[{"product_id": shop["ids"]["Bread"], "quantity": 5}])
    assert r.get_json()["ok"]
    with app.app_context():
        c = db.session.get(Client, shop["client"])
        assert c.balance == Decimal("5.00")
    assert b"Bread" in client.get("/t/alpha/app/debtors").data


def test_mobile_money_needs_a_code(client, shop):
    r = checkout(client, method="mobile", provider="M-Pesa", items=[{"product_id": shop["ids"]["Bread"], "quantity": 1}])
    assert r.status_code == 400
    r = checkout(client, method="mobile", provider="M-Pesa", payment_ref="QK7XY", items=[{"product_id": shop["ids"]["Bread"], "quantity": 1}])
    assert r.get_json()["ok"]


def test_pay_in_second_currency(app, client, shop):
    set_tenant(app, "alpha", currency="USD", alt_currency="ZWG", alt_rate=Decimal("26.5"))
    r = checkout(client, method="cash", tender_currency="ZWG", tendered="100",
                 items=[{"product_id": shop["ids"]["Bread"], "quantity": 3}])
    j = r.get_json()
    assert j["ok"], j
    with app.app_context():
        o = db.session.get(Order, j["order"])
        assert o.tender_currency == "ZWG"
        assert o.change == Decimal("4.60")  # 3.60 USD = 95.40 ZWG
        assert o.paid == Decimal("3.60")


def test_exclusive_tax_on_checkout(app, client, shop):
    set_tenant(app, "alpha", tax_rate=Decimal("15"), tax_inclusive=False)
    j = checkout(client, items=[{"product_id": shop["ids"]["Bread"], "quantity": 10}]).get_json()
    with app.app_context():
        o = db.session.get(Order, j["order"])
        assert o.total == Decimal("13.80") and o.tax == Decimal("1.80")
        assert Sale.query.filter_by(order_id=o.id).first().total == Decimal("13.80")


def test_other_business_products_are_refused(client, shop, two_tenants):
    r = checkout(client, items=[{"product_id": two_tenants["beta"]["product"], "quantity": 1}])
    assert r.status_code == 409


def test_sale_receipt_redirects_to_order(app, client, shop):
    j = checkout(client, items=[{"product_id": shop["ids"]["Bread"], "quantity": 1}]).get_json()
    with app.app_context():
        sid = Sale.query.filter_by(order_id=j["order"]).first().id
    r = client.get(f"/t/alpha/app/sales/{sid}/receipt")
    assert r.status_code == 302 and f"/orders/{j['order']}/receipt" in r.headers["Location"]


# ---------------------------------------------------------------- reports, settings, languages

def test_day_report(client, shop):
    checkout(client, items=[{"product_id": shop["ids"]["Bread"], "quantity": 2}])
    r = client.get("/t/alpha/app/reports/day")
    assert r.status_code == 200 and b"Bread" in r.data


def test_settings_change_currency_and_language(app, client, shop):
    r = client.post("/t/alpha/app/settings", data={
        "country": "MZ", "currency": "MZN", "locale": "pt_MZ", "timezone": "Africa/Maputo", "language": "pt",
        "tax_name": "IVA", "tax_rate": "16", "tax_mode": "inclusive", "alt_currency": "USD", "alt_rate": "0.0157"})
    assert r.status_code == 302
    with app.app_context():
        t = Tenant.query.filter_by(slug="alpha").first()
        assert t.currency == "MZN" and t.tax_rate == Decimal("16") and t.language == "pt"
    page = client.get("/t/alpha/app/").data.decode()
    assert "Painel" in page or "Vendas" in page
    assert "MTn" in page or "MZN" in page


def test_settings_reject_bad_values(app, client, shop):
    client.post("/t/alpha/app/settings", data={"currency": "XX", "locale": "en_ZW", "timezone": "Mars/Base", "tax_rate": "200"})
    with app.app_context():
        assert Tenant.query.filter_by(slug="alpha").first().currency is None


def test_member_language_choice(client, shop):
    client.post("/t/alpha/app/language", data={"lang": "fr", "next": "/t/alpha/app/"})
    assert "Ventes" in client.get("/t/alpha/app/").data.decode()


def test_arabic_is_right_to_left(client, shop):
    client.post("/t/alpha/app/language", data={"lang": "ar", "next": "/t/alpha/app/"})
    page = client.get("/t/alpha/app/register").data.decode()
    assert 'dir="rtl"' in page and "bootstrap.rtl.min.css" in page


def test_language_cookie_on_sign_in_page(client, two_tenants):
    client.post("/language", data={"lang": "sw", "next": "/t/alpha"})
    assert 'lang="sw"' in client.get("/t/alpha").data.decode()


def test_every_catalog_keeps_placeholders():
    import json
    import re
    from pathlib import Path

    for f in Path("app/translations").glob("*.json"):
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            assert set(re.findall(r"{\w+}", k)) == set(re.findall(r"{\w+}", v)), (f.name, k)


# ---------------------------------------------------------------- installable app

def test_manifest_and_service_worker(client, two_tenants):
    m = client.get("/t/alpha/manifest.webmanifest").get_json(force=True)
    assert m["start_url"] == "/t/alpha/app/register" and m["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and b"tylonerp-static" in sw.data
    assert client.get("/offline").status_code == 200


def test_pages_render_in_every_language(client, shop):
    from app.regional import LANGUAGES

    for code in LANGUAGES:
        client.post("/t/alpha/app/language", data={"lang": code, "next": "/"})
        for path in ("/t/alpha/app/", "/t/alpha/app/register", "/t/alpha/app/settings", "/t/alpha/app/reports/day",
                     "/t/alpha/app/sales", "/t/alpha/app/products"):
            assert client.get(path).status_code == 200, (code, path)
