"""One barcode, one product: every way a scan used to create a duplicate, plus undo and merge."""
import io

import pytest

from app import barcodes, db
from app.models import Product, Sale, StockMovement

from .conftest import login

SCAN = "/t/alpha/app/products/scan-in"


@pytest.fixture
def alpha(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    return client


def products(app, **kw):
    with app.app_context():
        return Product.query.filter_by(**kw).all()


# ---------------------------------------------------------------- barcode cleaning

@pytest.mark.parametrize("raw,clean", [
    ("012345678905", "0012345678905"),      # UPC-A becomes EAN-13
    (" 6009\t", "6009"), ("6009\r\n", "6009"),
    ("]E06001234500059", "6001234500059"),  # scanner symbology prefix
    ("ABC-123", "ABC-123"), ("", None), (None, None),
])
def test_clean(raw, clean):
    assert barcodes.clean(raw) == clean


def test_variants_match_upc_ean_and_lost_zeros():
    v = barcodes.variants("0012345678905")
    assert {"012345678905", "0012345678905", "12345678905", "00012345678905"} <= set(v)
    assert barcodes.key("012345678905") == barcodes.key("12345678905") == barcodes.key("0012345678905")


# ---------------------------------------------------------------- the duplicate paths, now closed

def test_scanning_a_typed_product_links_instead_of_duplicating(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Sugar 2kg", "price": "3", "stock": "5"})
    r = alpha.post(SCAN, json={"barcode": "6001234500059", "name": "sugar  2KG", "price": "3"}).json
    assert r["linked"] and r["product"]["stock"] == 6
    [p] = products(app, name="Sugar 2kg")
    assert p.barcode == "6001234500059"


def test_unknown_code_can_be_linked_to_a_chosen_product(alpha, app):
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Tea 100s", "price": "2", "stock": "1"})
    pid = products(app, name="Tea 100s")[0].id
    r = alpha.post(SCAN, json={"barcode": "777", "product_id": pid, "quantity": 3}).json
    assert r["linked"] and r["product"]["stock"] == 4
    assert alpha.post(SCAN, json={"barcode": "777"}).json["product"]["stock"] == 5


def test_linking_refuses_a_product_that_has_another_barcode(alpha, two_tenants):
    r = alpha.post(SCAN, json={"barcode": "999", "product_id": two_tenants["alpha"]["product"]})
    assert r.status_code == 409 and "already has barcode" in r.json["error"]


def test_name_of_product_with_another_barcode_is_refused(alpha, app):
    r = alpha.post(SCAN, json={"barcode": "999", "name": "alpha soap", "price": "1"})
    assert r.status_code == 409 and len(products(app, name="alpha soap")) == 1


def test_upc_and_ean_reads_are_one_product(alpha, app):
    alpha.post(SCAN, json={"barcode": "012345678905", "name": "Juice", "price": "1"})
    r = alpha.post(SCAN, json={"barcode": "0012345678905"}).json
    assert r["found"] and r["product"]["stock"] == 2 and len(products(app, tenant_id=1)) == 2


def test_scanner_noise_is_ignored(alpha, app):
    alpha.post(SCAN, json={"barcode": "6009\t", "name": "Tea", "price": "1"})
    assert alpha.post(SCAN, json={"barcode": "]E06009"}).json["product"]["stock"] == 2


def test_old_rows_stored_as_upc_still_match(alpha, app, two_tenants):
    with app.app_context():
        db.session.add(Product(tenant_id=two_tenants["alpha"]["tenant"], name="Old", price=1, stock=0, barcode="012345678905"))
        db.session.commit()
    assert alpha.post(SCAN, json={"barcode": "0012345678905"}).json["product"]["name"] == "Old"
    r = alpha.post("/t/alpha/app/quick-sell/match", json={"barcode": "12345678905"}).json
    assert r["matches"][0]["name"] == "Old"


def test_photo_registration_checks_names(alpha, app):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    alpha.post("/t/alpha/app/products", content_type="multipart/form-data", data={
        "method": "photo", "name": "Alpha Soap", "price": "1", "stock": "1", "signature": "0" * 70,
        "photo": (io.BytesIO(png), "p.png")})
    assert len(products(app, tenant_id=1)) == 1


def test_manual_barcode_is_matched_like_a_scan(alpha, app):
    alpha.post(SCAN, json={"barcode": "012345678905", "name": "Juice", "price": "1"})
    alpha.post("/t/alpha/app/products", data={"method": "manual", "name": "Juice two", "price": "1",
                                              "barcode": "0012345678905"})
    assert products(app, name="Juice two") == []


def test_import_matches_upc_against_ean(alpha, app):
    alpha.post(SCAN, json={"barcode": "012345678905", "name": "Juice", "price": "1"})
    alpha.post("/t/alpha/app/products/import", data={"rows": "barcode,quantity\n12345678905,10"})
    [p] = products(app, name="Juice")
    assert p.stock == 11 and len(products(app, tenant_id=1)) == 2


# ---------------------------------------------------------------- double counting

def test_same_scan_id_counts_once(alpha, two_tenants):
    body = {"barcode": "alpha-1", "scan_id": "abc123"}
    first = alpha.post(SCAN, json=body).json
    again = alpha.post(SCAN, json=body).json
    assert first["product"]["stock"] == 11 and again["repeat"] and again["product"]["stock"] == 11


def test_double_tap_on_register_creates_one_product_and_one_count(alpha, app):
    body = {"barcode": "NEW1", "name": "Milk", "price": "1", "scan_id": "reg-1"}
    alpha.post(SCAN, json=body)
    alpha.post(SCAN, json=body)
    [p] = products(app, name="Milk")
    assert p.stock == 1


# ---------------------------------------------------------------- undo

def test_undo_takes_a_scan_back(alpha, app):
    r = alpha.post(SCAN, json={"barcode": "alpha-1", "quantity": 4}).json
    u = alpha.post(f"/t/alpha/app/stock/{r['movement']}/undo", json={}).json
    assert u["ok"] and u["stock"] == 10
    with app.app_context():
        assert StockMovement.query.filter_by(source="scan").count() == 0
    assert alpha.post(f"/t/alpha/app/stock/{r['movement']}/undo", json={}).status_code == 404


def test_undo_refuses_when_stock_was_already_sold(alpha, two_tenants):
    r = alpha.post(SCAN, json={"barcode": "alpha-1", "quantity": 2}).json
    alpha.post("/t/alpha/app/quick-sell/confirm", json={"product_id": two_tenants["alpha"]["product"], "quantity": 11})
    assert alpha.post(f"/t/alpha/app/stock/{r['movement']}/undo", json={}).status_code == 409


def test_undo_is_tenant_scoped(client, two_tenants):
    login(client, "beta", two_tenants["beta"]["email"])
    mid = client.post("/t/beta/app/products/scan-in", json={"barcode": "beta-1"}).json["movement"]
    client.post("/t/beta/logout")
    login(client, "alpha", two_tenants["alpha"]["email"])
    assert client.post(f"/t/alpha/app/stock/{mid}/undo", json={}).status_code == 404


# ---------------------------------------------------------------- finding and merging existing duplicates

def make_dupes(app, tid):
    with app.app_context():
        a = Product(tenant_id=tid, name="Rice 5kg", price=6, stock=4, barcode="6005")
        b = Product(tenant_id=tid, name="rice  5KG", price=6, stock=3)
        db.session.add_all([a, b])
        db.session.flush()
        db.session.add(Sale(tenant_id=tid, product_id=b.id, product_name=b.name, quantity=1, unit_price=6, paid=6))
        db.session.add(StockMovement(tenant_id=tid, product_id=b.id, quantity=3, source="restock"))
        db.session.commit()
        return a.id, b.id


def test_stock_page_lists_duplicates(alpha, app, two_tenants):
    make_dupes(app, two_tenants["alpha"]["tenant"])
    assert b"Possible duplicates" in alpha.get("/t/alpha/app/products").data


def test_merge_moves_stock_sales_and_history(alpha, app, two_tenants):
    keep, drop = make_dupes(app, two_tenants["alpha"]["tenant"])
    alpha.post("/t/alpha/app/products/merge", data={"keep": keep, "ids": [keep, drop]})
    with app.app_context():
        assert db.session.get(Product, drop) is None
        p = db.session.get(Product, keep)
        assert p.stock == 7 and p.barcode == "6005"
        assert Sale.query.filter_by(product_id=keep).count() == 1
        assert StockMovement.query.filter_by(product_id=keep).count() == 1
    assert b"Possible duplicates" not in alpha.get("/t/alpha/app/products").data


def test_merge_keeps_the_barcode_from_the_dropped_product(alpha, app, two_tenants):
    keep, drop = make_dupes(app, two_tenants["alpha"]["tenant"])
    alpha.post("/t/alpha/app/products/merge", data={"keep": drop, "ids": [keep, drop]})
    with app.app_context():
        assert db.session.get(Product, drop).barcode == "6005"


def test_merge_refuses_different_barcodes(alpha, app, two_tenants):
    with app.app_context():
        a = Product(tenant_id=two_tenants["alpha"]["tenant"], name="Oil", price=1, stock=1, barcode="1")
        b = Product(tenant_id=two_tenants["alpha"]["tenant"], name="oil", price=1, stock=1, barcode="2")
        db.session.add_all([a, b])
        db.session.commit()
        ids = [a.id, b.id]
    alpha.post("/t/alpha/app/products/merge", data={"keep": ids[0], "ids": ids})
    assert len(products(app, price=1)) == 2


def test_merge_is_admin_only_and_tenant_scoped(client, app, two_tenants):
    keep, drop = make_dupes(app, two_tenants["alpha"]["tenant"])
    login(client, "beta", two_tenants["beta"]["email"])
    client.post("/t/beta/app/products/merge", data={"keep": two_tenants["beta"]["product"], "ids": [keep, drop]})
    with app.app_context():
        assert db.session.get(Product, drop) is not None
