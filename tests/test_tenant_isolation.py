"""A signed-in user of one tenant must never read or change another tenant's data."""
import pytest

from app import db
from app.models import Product, Sale

from .conftest import login


@pytest.fixture
def alpha(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    return client


def test_own_workspace_loads(alpha):
    assert alpha.get("/t/alpha/app/").status_code == 200


@pytest.mark.parametrize("path", ["", "products", "clients", "sales", "debtors", "members", "quick-sell"])
def test_other_tenants_workspace_is_not_reachable(alpha, path):
    # The session cookie is scoped to /t/alpha, so beta's pages see an anonymous visitor
    r = alpha.get(f"/t/beta/app/{path}")
    assert r.status_code == 302 and "/t/beta" in r.headers["Location"] and "/app" not in r.headers["Location"].split("?")[0]


def test_cannot_restock_other_tenants_product(alpha, app, two_tenants):
    pid = two_tenants["beta"]["product"]
    assert alpha.post(f"/t/alpha/app/products/{pid}/restock", data={"qty": "5"}).status_code == 404
    with app.app_context():
        assert db.session.get(Product, pid).stock == 10


def test_cannot_delete_other_tenants_product(alpha, app, two_tenants):
    pid = two_tenants["beta"]["product"]
    assert alpha.post(f"/t/alpha/app/products/{pid}/delete").status_code == 404
    with app.app_context():
        assert db.session.get(Product, pid) is not None


def test_cannot_sell_other_tenants_product(alpha, app, two_tenants):
    r = alpha.post("/t/alpha/app/quick-sell/confirm",
                   json={"product_id": two_tenants["beta"]["product"], "quantity": 1})
    assert r.status_code == 404
    with app.app_context():
        assert Sale.query.count() == 0


def test_cannot_view_other_tenants_receipt_or_photo(alpha, app, two_tenants):
    with app.app_context():
        p = db.session.get(Product, two_tenants["beta"]["product"])
        s = Sale(tenant_id=p.tenant_id, product_id=p.id, product_name=p.name, quantity=1, unit_price=5, paid=5)
        db.session.add(s)
        db.session.commit()
        sid = s.id
    assert alpha.get(f"/t/alpha/app/sales/{sid}/receipt").status_code == 404
    assert alpha.get(f"/t/alpha/app/products/{two_tenants['beta']['product']}/photo").status_code == 404


def test_cannot_record_payment_on_other_tenants_sale(alpha, app, two_tenants):
    with app.app_context():
        p = db.session.get(Product, two_tenants["beta"]["product"])
        s = Sale(tenant_id=p.tenant_id, product_id=p.id, product_name=p.name, quantity=2, unit_price=5, paid=0)
        db.session.add(s)
        db.session.commit()
        sid = s.id
    assert alpha.post(f"/t/alpha/app/sales/{sid}/payment", data={"amount": "5"}).status_code == 404
    with app.app_context():
        assert db.session.get(Sale, sid).paid == 0


def test_barcode_scan_in_is_scoped_to_tenant(alpha, app, two_tenants):
    # beta's barcode is unknown to alpha, so it must not touch beta's stock
    r = alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "beta-1"})
    assert r.json == {"found": False, "barcode": "beta-1"}
    with app.app_context():
        assert db.session.get(Product, two_tenants["beta"]["product"]).stock == 10
