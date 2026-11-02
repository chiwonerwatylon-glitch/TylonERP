"""Mobile API: sign-in, catalog, and offline changes uploaded later (each exactly once)."""
from decimal import Decimal

import pytest

from app import db
from app.models import Client, Product, Sale, StockMovement, SyncOp, User


@pytest.fixture
def token(client, two_tenants):
    r = client.post("/api/v1/login", json={"slug": "alpha", "email": two_tenants["alpha"]["email"], "password": "pw-12345678"})
    assert r.status_code == 200
    return r.json["token"]


def sync(client, token, *ops):
    return client.post("/api/v1/sync", json={"ops": list(ops)}, headers={"Authorization": f"Bearer {token}"})


def op(op_id, kind, **data):
    return {"op_id": op_id, "kind": kind, "data": data}


# ---------------------------------------------------------------- sign in

def test_login_returns_tenant(client, two_tenants):
    r = client.post("/api/v1/login", json={"slug": "alpha", "email": two_tenants["alpha"]["email"], "password": "pw-12345678"}).json
    assert r["ok"] and r["tenant"]["slug"] == "alpha" and r["user"]["role"] == "admin" and r["token"]


@pytest.mark.parametrize("slug,password", [("alpha", "wrong"), ("beta", "pw-12345678"), ("nope", "pw-12345678")])
def test_login_rejects_wrong_details(client, two_tenants, slug, password):
    r = client.post("/api/v1/login", json={"slug": slug, "email": two_tenants["alpha"]["email"], "password": password})
    assert r.status_code == 401 and r.json["error"] == "Incorrect business, email or password."


def test_superadmin_cannot_use_phone_api(client, app):
    r = client.post("/api/v1/login", json={"slug": "", "email": "admin@erp.co.zw", "password": "admin-pass-123"})
    assert r.status_code == 401


def test_bad_or_missing_token(client):
    assert client.get("/api/v1/catalog").status_code == 401
    assert client.get("/api/v1/catalog", headers={"Authorization": "Bearer junk"}).json["signed_out"] is True


def test_password_change_signs_phone_out(client, app, token, two_tenants):
    with app.app_context():
        u = User.query.filter_by(email=two_tenants["alpha"]["email"]).one()
        u.set_password("new-password-1")
        db.session.commit()
    assert client.get("/api/v1/catalog", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_mobile_session_signs_web_view_in(client, token):
    r = client.post("/t/alpha/mobile-session", data={"token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/t/alpha/app/")
    assert client.get("/t/alpha/app/").status_code == 200


def test_mobile_session_rejects_other_tenant(client, token):
    r = client.post("/t/beta/mobile-session", data={"token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/t/beta")


# ---------------------------------------------------------------- catalog

def test_catalog_is_tenant_scoped(client, token):
    c = client.get("/api/v1/catalog", headers={"Authorization": f"Bearer {token}"}).json
    assert [p["name"] for p in c["products"]] == ["alpha soap"] and [x["name"] for x in c["clients"]] == ["alpha client"]
    assert c["products"][0]["price"] == "5.00"


# ---------------------------------------------------------------- offline changes

def test_offline_sale_is_recorded_once(client, app, token, two_tenants):
    pid = two_tenants["alpha"]["product"]
    sale = op("sale-1", "sale.create", product=f"s:{pid}", quantity=3, unit_price="5", at=1_700_000_000_000)
    first = sync(client, token, sale).json["results"][0]
    again = sync(client, token, sale).json["results"][0]
    assert first["ok"] and again["repeat"] and again["server_id"] == first["server_id"]
    with app.app_context():
        assert Sale.query.count() == 1 and db.session.get(Product, pid).stock == 7


def test_records_made_offline_link_up(client, app, token):
    """A client and a product created offline, then a credit sale and a payment that refer to them."""
    r = sync(client, token,
             op("c1", "client.create", name="Chipo's Tuckshop", phone="0772114905"),
             op("p1", "product.create", name="Rice 5kg", price="6.50", barcode="012345678905", stock=10),
             op("s1", "sale.create", product="l:p1", quantity=2, paid="5", client="l:c1"),
             op("a1", "stock.add", product="l:p1", quantity=4, source="scan")).json
    assert all(x["ok"] for x in r["results"]), r["results"]
    sale_id = r["results"][2]["server_id"]
    pay = sync(client, token, op("pay1", "payment.create", sale=f"s:{sale_id}", amount="3")).json["results"][0]
    assert pay["ok"] and pay["balance"] == "5.00"
    with app.app_context():
        p = Product.query.filter_by(name="Rice 5kg").one()
        assert p.stock == 12 and p.barcode == "0012345678905"
        s = db.session.get(Sale, sale_id)
        assert s.client.name == "Chipo's Tuckshop" and s.paid == Decimal("8.00")
        assert StockMovement.query.filter_by(product_id=p.id).count() == 2


def test_offline_product_matching_an_existing_one_is_not_duplicated(client, app, token):
    r = sync(client, token, op("p2", "product.create", name="Alpha  Soap", price="1", stock=5)).json["results"][0]
    assert r["ok"] and "already existed" in r["warning"]
    with app.app_context():
        assert Product.query.filter_by(tenant_id=1).count() == 1 and Product.query.filter_by(tenant_id=1).one().stock == 15


def test_offline_client_with_existing_name_is_reused(client, app, token, two_tenants):
    r = sync(client, token, op("c2", "client.create", name="ALPHA CLIENT")).json["results"][0]
    assert r["server_id"] == two_tenants["alpha"]["client"]


def test_oversold_offline_is_kept_with_a_warning(client, app, token, two_tenants):
    r = sync(client, token, op("s2", "sale.create", product=f"s:{two_tenants['alpha']['product']}", quantity=12)).json
    assert r["results"][0]["ok"] and "more were sold" in r["results"][0]["warning"]
    assert r["catalog"]["products"][0]["stock"] == -2


def test_credit_sale_without_client_fails_cleanly(client, app, token, two_tenants):
    r = sync(client, token, op("s3", "sale.create", product=f"s:{two_tenants['alpha']['product']}", quantity=1, paid="0")).json
    assert r["results"][0] == {"ok": False, "error": "A part-paid or credit sale needs a client.", "op_id": "s3"}
    with app.app_context():
        assert Sale.query.count() == 0 and SyncOp.query.count() == 1  # failure stored: a retry gets the same answer


def test_onemoney_needs_number_and_code(client, token, two_tenants):
    pid = two_tenants["alpha"]["product"]
    bad = sync(client, token, op("o1", "sale.create", product=f"s:{pid}", quantity=1, method="onemoney")).json
    good = sync(client, token, op("o2", "sale.create", product=f"s:{pid}", quantity=1, method="onemoney",
                                  phone="0711234567", payment_ref="MP123")).json
    assert not bad["results"][0]["ok"] and good["results"][0]["ok"]


def test_payment_more_than_owed_is_capped(client, app, token, two_tenants):
    r = sync(client, token, op("s4", "sale.create", product=f"s:{two_tenants['alpha']['product']}", quantity=1, paid="0",
                               client=f"s:{two_tenants['alpha']['client']}")).json
    sid = r["results"][0]["server_id"]
    p = sync(client, token, op("pay2", "payment.create", sale=f"s:{sid}", amount="99")).json["results"][0]
    assert p["ok"] and "Only 5.00 was owed" in p["warning"] and p["balance"] == "0.00"


def test_cannot_touch_another_tenants_records(client, app, token, two_tenants):
    r = sync(client, token, op("x1", "stock.add", product=f"s:{two_tenants['beta']['product']}", quantity=5)).json
    assert not r["results"][0]["ok"]
    with app.app_context():
        assert db.session.get(Product, two_tenants["beta"]["product"]).stock == 10


def test_unknown_change_and_bad_input(client, token):
    r = sync(client, token, op("u1", "teleport"), {"kind": "sale.create"}).json["results"]
    assert not r[0]["ok"] and r[1]["error"] == "Missing op_id."
    assert client.post("/api/v1/sync", json={"ops": "x"}, headers={"Authorization": f"Bearer {token}"}).status_code == 400


def test_debts_in_catalog(client, token, two_tenants):
    sync(client, token, op("s5", "sale.create", product=f"s:{two_tenants['alpha']['product']}", quantity=2, paid="4",
                           client=f"s:{two_tenants['alpha']['client']}"))
    c = client.get("/api/v1/catalog", headers={"Authorization": f"Bearer {token}"}).json
    assert c["debts"][0]["balance"] == "6.00" and c["debts"][0]["client"] == "alpha client"
    assert Client  # imported for clarity of the fixture data
