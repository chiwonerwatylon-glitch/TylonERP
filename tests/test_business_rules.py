from decimal import Decimal

import pytest

from app import db
from app.models import Client, Product, Sale, Tenant, User

from .conftest import login


@pytest.fixture
def alpha(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    return client


def sell(c, ids, **kw):
    return c.post("/t/alpha/app/quick-sell/confirm", json={"product_id": ids["alpha"]["product"], **kw})


def test_cash_sale_reduces_stock(alpha, app, two_tenants):
    r = sell(alpha, two_tenants, quantity=3)
    assert r.status_code == 200 and r.json["total"] == "15.00" and r.json["stock"] == 7
    with app.app_context():
        assert Sale.query.one().kind == "Cash"


def test_cannot_oversell(alpha, app, two_tenants):
    assert sell(alpha, two_tenants, quantity=11).status_code == 409
    with app.app_context():
        assert db.session.get(Product, two_tenants["alpha"]["product"]).stock == 10


def test_quantity_required(alpha, two_tenants):
    assert sell(alpha, two_tenants, quantity=0).status_code == 400


def test_credit_sale_needs_client(alpha, two_tenants):
    assert sell(alpha, two_tenants, quantity=1, paid="0").status_code == 400


def test_credit_sale_with_client_shows_as_debt(alpha, app, two_tenants):
    r = sell(alpha, two_tenants, quantity=2, paid="4", client_id=two_tenants["alpha"]["client"])
    assert r.status_code == 200
    with app.app_context():
        s = Sale.query.one()
        assert (s.kind, s.balance) == ("Part-paid", Decimal("6"))
    assert b"alpha client" in alpha.get("/t/alpha/app/debtors").data


def test_payment_rules(alpha, app, two_tenants):
    sell(alpha, two_tenants, quantity=2, paid="0", client_id=two_tenants["alpha"]["client"])
    with app.app_context():
        sid = Sale.query.one().id
    alpha.post(f"/t/alpha/app/sales/{sid}/payment", data={"amount": "999"})  # more than owed: rejected
    alpha.post(f"/t/alpha/app/sales/{sid}/payment", data={"amount": "4"})
    with app.app_context():
        assert db.session.get(Sale, sid).paid == Decimal("4")


def test_restock_adds_quantity(alpha, app, two_tenants):
    pid = two_tenants["alpha"]["product"]
    alpha.post(f"/t/alpha/app/products/{pid}/restock", data={"qty": "5"})
    with app.app_context():
        assert db.session.get(Product, pid).stock == 15


def test_scan_in_increments_known_barcode(alpha, app, two_tenants):
    r = alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "alpha-1"})
    assert r.json["found"] and r.json["product"]["stock"] == 11


def test_scan_in_creates_unknown_barcode_once(alpha, app):
    body = {"barcode": "NEW1", "name": "Milk", "price": "2.50"}
    assert alpha.post("/t/alpha/app/products/scan-in", json=body).json["created"] is True
    again = alpha.post("/t/alpha/app/products/scan-in", json=body).json
    assert again["product"]["stock"] == 2
    with app.app_context():
        assert Product.query.filter_by(barcode="NEW1").count() == 1


def test_duplicate_barcode_rejected_on_add(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "barcode", "name": "Dup", "price": "1", "barcode": "alpha-1"})
    with app.app_context():
        assert Product.query.filter_by(name="Dup").count() == 0


def test_plan_user_limit_enforced(alpha, app, two_tenants):
    for i in range(3):  # starter allows 3 members, owner is one
        alpha.post("/t/alpha/app/members", data={"name": f"U{i}", "email": f"u{i}@alpha.test", "role": "staff"})
    with app.app_context():
        assert User.query.filter_by(tenant_id=two_tenants["alpha"]["tenant"]).count() == 3


def test_staff_cannot_manage_members(client, app, two_tenants):
    with app.app_context():
        u = User(tenant_id=two_tenants["alpha"]["tenant"], email="s@alpha.test", name="Staff", role="staff")
        u.set_password("pw-12345678")
        db.session.add(u)
        db.session.commit()
    login(client, "alpha", "s@alpha.test")
    assert client.get("/t/alpha/app/members").status_code == 403


def test_branding_rejects_non_image(alpha):
    import io
    r = alpha.post("/t/alpha/app/branding", data={"logo": (io.BytesIO(b"not an image"), "x.png")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert b"PNG, JPEG or WebP" in r.data


def test_admin_creates_tenant_with_temp_password(client, app):
    client.post("/login", data={"email": "admin@erp.co.zw", "password": "admin-pass-123"})
    r = client.post("/admin/tenants/new", data={"name": "Gamma", "slug": "gamma", "email": "g@gamma.test", "plan": "growth"})
    assert r.status_code == 200
    with app.app_context():
        u = User.query.filter_by(email="g@gamma.test").one()
        assert u.must_change_password and Tenant.query.filter_by(slug="gamma").one().max_users == 15
        assert Client.query.count() == 0
