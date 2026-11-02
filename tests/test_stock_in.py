"""Ways of adding stock: manual entry, scan with a quantity, CSV import, and the stock-in history."""
import io
from decimal import Decimal

import pytest

from app import db
from app.models import Product, Sale, StockMovement

from .conftest import login


@pytest.fixture
def alpha(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    return client


def product(app, **kw):
    with app.app_context():
        return Product.query.filter_by(**kw).first()


# ---------------------------------------------------------------- manual entry

def test_manual_product_needs_no_photo(alpha, app):
    r = alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Sugar 2kg", "price": "3.10",
                                                  "stock": "40", "sku": "SUG-2", "barcode": "600111"})
    assert r.status_code == 302
    p = product(app, name="Sugar 2kg")
    assert (p.stock, p.method, p.sku, p.barcode, p.price) == (40, "manual", "SUG-2", "600111", Decimal("3.10"))
    with app.app_context():
        m = StockMovement.query.filter_by(product_id=p.id).one()
        assert (m.quantity, m.source) == (40, "new")


def test_manual_duplicate_name_is_refused(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "ALPHA SOAP", "price": "1", "stock": "1"})
    with app.app_context():
        assert Product.query.filter(db.func.lower(Product.name) == "alpha soap").count() == 1


def test_manual_rejects_bad_quantity(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Tea", "price": "1", "stock": "-3"})
    assert product(app, name="Tea") is None


# ---------------------------------------------------------------- scanning with a quantity

def test_scan_in_with_quantity_counts_a_carton(alpha, app, two_tenants):
    r = alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "alpha-1", "quantity": "24"})
    assert r.json["added"] == 24 and r.json["product"]["stock"] == 34
    with app.app_context():
        assert StockMovement.query.filter_by(source="scan").one().quantity == 24


def test_scan_in_rejects_bad_quantity(alpha, app):
    assert alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "alpha-1", "quantity": "0"}).status_code == 400
    assert alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "alpha-1", "quantity": "x"}).status_code == 400
    assert product(app, barcode="alpha-1").stock == 10


def test_scan_in_new_barcode_with_quantity(alpha, app):
    r = alpha.post("/t/alpha/app/products/scan-in",
                   json={"barcode": "NEW9", "name": "Juice", "price": "1.20", "quantity": 6}).json
    assert r["created"] and r["product"]["stock"] == 6


def test_scan_in_missing_details_reports_error(alpha):
    r = alpha.post("/t/alpha/app/products/scan-in", json={"barcode": "NEW8", "name": "", "price": ""}).json
    assert r["found"] is False and r["error"]


# ---------------------------------------------------------------- import

def test_import_pasted_rows_creates_and_restocks(alpha, app):
    rows = ("name,price,quantity,barcode,sku\n"
            "alpha soap,9.99,5,,\n"            # existing product by name: restock, price unchanged
            "Rice 5kg,6.50,10,6009,RICE5\n"    # new product with a barcode
            "Salt,0.80,30,,\n")                # new product, manual
    r = alpha.post("/t/alpha/app/products/import", data={"rows": rows})
    assert r.status_code == 302 and "tab=import" in r.headers["Location"]
    with app.app_context():
        soap = Product.query.filter_by(name="alpha soap").one()
        assert (soap.stock, soap.price) == (15, Decimal("5.00"))
        rice = Product.query.filter_by(barcode="6009").one()
        assert (rice.name, rice.stock, rice.sku, rice.method) == ("Rice 5kg", 10, "RICE5", "barcode")
        assert Product.query.filter_by(name="Salt").one().method == "manual"
        assert StockMovement.query.filter_by(source="import").count() == 1


def test_import_matches_by_barcode_and_can_update_prices(alpha, app):
    alpha.post("/t/alpha/app/products/import", data={"rows": "barcode;quantity;price\nalpha-1;3;7.25",
                                                     "update_prices": "1"})
    p = product(app, barcode="alpha-1")
    assert (p.stock, p.price) == (13, Decimal("7.25"))


def test_import_csv_file_without_header(alpha, app):
    data = {"file": (io.BytesIO(b"\xef\xbb\xbfBread,1.10,20\nMilk,0.95,12\n"), "delivery.csv")}
    alpha.post("/t/alpha/app/products/import", data=data, content_type="multipart/form-data")
    assert product(app, name="Bread").stock == 20 and product(app, name="Milk").stock == 12


def test_import_skips_bad_rows_but_keeps_good_ones(alpha, app):
    rows = "name,price,quantity\nGood,1,4\nNo price,,4\nBad qty,1,lots\nBad price,abc,1\n"
    r = alpha.post("/t/alpha/app/products/import", data={"rows": rows}, follow_redirects=True)
    assert product(app, name="Good").stock == 4
    for name in ("No price", "Bad qty", "Bad price"):
        assert product(app, name=name) is None
    assert b"Line 3" in r.data and b"Line 4" in r.data and b"Line 5" in r.data


def test_import_same_new_product_twice_in_one_file(alpha, app):
    alpha.post("/t/alpha/app/products/import", data={"rows": "name,price,quantity\nOil,4,2\noil,4,3\n"})
    with app.app_context():
        assert Product.query.filter(db.func.lower(Product.name) == "oil").one().stock == 5


def test_import_stays_inside_tenant(alpha, app, two_tenants):
    alpha.post("/t/alpha/app/products/import", data={"rows": "barcode,quantity\nbeta-1,50"})
    assert product(app, barcode="beta-1").stock == 10  # beta's product untouched
    with app.app_context():  # alpha got a new product of its own instead
        assert Product.query.filter_by(tenant_id=two_tenants["alpha"]["tenant"], barcode="beta-1").count() == 0


def test_import_template_downloads(alpha):
    r = alpha.get("/t/alpha/app/products/import-template.csv")
    assert r.status_code == 200 and r.data.startswith(b"name,price,quantity")


# ---------------------------------------------------------------- restock and history

def test_restock_is_recorded_and_shown(alpha, app, two_tenants):
    pid = two_tenants["alpha"]["product"]
    alpha.post(f"/t/alpha/app/products/{pid}/restock", data={"qty": "7"})
    page = alpha.get("/t/alpha/app/products").data
    assert b"Recent stock added" in page and b"+7" in page


def test_restock_rejects_huge_quantity(alpha, app, two_tenants):
    pid = two_tenants["alpha"]["product"]
    alpha.post(f"/t/alpha/app/products/{pid}/restock", data={"qty": "99999999999"})
    assert product(app, id=pid).stock == 10


# ---------------------------------------------------------------- bug fixes

@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1e20"])
def test_odd_amounts_are_rejected_not_crashing(alpha, app, two_tenants, amount):
    r = alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Odd", "price": amount, "stock": "1"})
    assert r.status_code == 302 and product(app, name="Odd") is None


def test_amounts_round_to_cents(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Cents", "price": "1.005", "stock": "1"})
    assert product(app, name="Cents").price == Decimal("1.01")


def test_refunded_sale_is_not_a_debt(alpha, app, two_tenants):
    with app.app_context():
        s = Sale(tenant_id=two_tenants["alpha"]["tenant"], client_id=two_tenants["alpha"]["client"],
                 product_id=two_tenants["alpha"]["product"], product_name="alpha soap", quantity=2,
                 unit_price=5, paid=0, payment_method="ecocash", payment_status="refunded")
        db.session.add(s)
        db.session.commit()
        sid = s.id
        assert s.balance == 0
    assert b"alpha client" not in alpha.get("/t/alpha/app/debtors").data
    alpha.post(f"/t/alpha/app/sales/{sid}/payment", data={"amount": "5"})
    with app.app_context():
        assert db.session.get(Sale, sid).paid == 0
    assert b'Credit <span class="opacity-75 ms-1">0</span>' in alpha.get("/t/alpha/app/sales").data


def test_tenant_user_on_admin_login_goes_to_their_page(client, two_tenants):
    r = client.post("/login", data={"email": two_tenants["alpha"]["email"], "password": "pw-12345678"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/t/alpha")
