from types import SimpleNamespace

import pytest
import requests

from app import db
from app.models import Product, Sale
from app.payments import EcoCashClient, normalise_msisdn

from .conftest import login


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeHttp:
    """Stands in for requests: replays queued responses and records the calls."""

    def __init__(self, *responses):
        self.queue, self.calls = list(responses), []

    def request(self, method, url, json=None, auth=None, timeout=None):
        self.calls.append((method, url, json, auth))
        r = self.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


CHARGED = FakeResp(200, {"transactionOperationStatus": "Charged", "responseCode": "00",
                         "ecocashReference": "MP1.T1"})
DECLINED = FakeResp(422, {"responseCode": "INSUFFICIENT", "message": "Insufficient funds"})


def settings(**kw):
    base = dict(ecocash_base_url="https://eco.test/v1", ecocash_charge_path="/transactions/amount",
                ecocash_username="u", ecocash_password="p", ecocash_merchant_code="001",
                ecocash_merchant_pin="0000", ecocash_merchant_number="788732685", ecocash_merchant_name="Shop",
                ecocash_super_merchant_name="ECOCASH", ecocash_terminal_id="T1", ecocash_location="Harare",
                ecocash_currency="USD", ecocash_notify_url=None, ecocash_timeout=5)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def gateway(app, monkeypatch):
    def install(*responses):
        http = FakeHttp(*responses)
        monkeypatch.setattr("app.workspace.ecocash", lambda: EcoCashClient(settings(), http))
        return http
    return install


@pytest.fixture
def alpha(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    return client


def sell(c, ids, **kw):
    return c.post("/t/alpha/app/quick-sell/confirm", json={"product_id": ids["alpha"]["product"], **kw})


def test_msisdn_normalised():
    for raw in ("0773047653", "+263 77 304 7653", "263773047653", "773047653"):
        assert normalise_msisdn(raw) == "773047653"


def test_ecocash_charge_payload_and_sale(alpha, app, two_tenants, gateway):
    http = gateway(CHARGED)
    r = sell(alpha, two_tenants, quantity=2, method="ecocash", phone="0773047653")
    assert r.status_code == 200 and r.json["stock"] == 8
    method, url, body, auth = http.calls[0]
    assert (method, url, auth) == ("POST", "https://eco.test/v1/transactions/amount", ("u", "p"))
    assert body["endUserId"] == "773047653" and body["tranType"] == "MER"
    assert body["paymentAmount"]["charginginformation"]["amount"] == 10.0
    with app.app_context():
        s = Sale.query.one()
        assert (s.payment_method, s.payment_status, s.payment_ref) == ("ecocash", "paid", "MP1.T1")
        assert s.paid == s.total and s.kind == "Cash"


def test_declined_charge_keeps_no_sale_and_stock(alpha, app, two_tenants, gateway):
    gateway(DECLINED)
    r = sell(alpha, two_tenants, quantity=2, method="ecocash", phone="0773047653")
    assert r.status_code == 400 and "Insufficient funds" in r.json["error"]
    with app.app_context():
        assert Sale.query.count() == 0
        assert db.session.get(Product, two_tenants["alpha"]["product"]).stock == 10


def test_ecocash_needs_valid_number_and_credentials(alpha, app, two_tenants, gateway, monkeypatch):
    gateway()
    assert "EcoCash number" in sell(alpha, two_tenants, quantity=1, method="ecocash", phone="0711234567").json["error"]
    monkeypatch.setattr("app.workspace.ecocash", lambda: EcoCashClient(settings(ecocash_username=None)))
    assert "not set up" in sell(alpha, two_tenants, quantity=1, method="ecocash", phone="0773047653").json["error"]


def test_timeout_leaves_pending_then_lookup_confirms(alpha, app, two_tenants, gateway):
    http = gateway(requests.Timeout("slow"), CHARGED)
    r = sell(alpha, two_tenants, quantity=1, method="ecocash", phone="0773047653")
    assert r.status_code == 200 and "unconfirmed" in r.json["warning"]
    with app.app_context():
        s = Sale.query.one()
        sid, corr = s.id, s.payment_correlator
        assert s.payment_status == "pending" and s.kind == "Pending" and s.paid == 0
    alpha.post(f"/t/alpha/app/sales/{sid}/check-payment")
    assert http.calls[1][0] == "GET" and http.calls[1][1].endswith(f"/773047653/transactions/amount/{corr}")
    with app.app_context():
        assert Sale.query.one().payment_status == "paid"


def test_lookup_not_found_cancels_pending_sale(alpha, app, two_tenants, gateway):
    gateway(requests.Timeout("slow"), FakeResp(400, {"responseCode": "888803"}))
    sell(alpha, two_tenants, quantity=3, method="ecocash", phone="0773047653")
    with app.app_context():
        sid = Sale.query.one().id
    alpha.post(f"/t/alpha/app/sales/{sid}/check-payment")
    with app.app_context():
        assert Sale.query.count() == 0
        assert db.session.get(Product, two_tenants["alpha"]["product"]).stock == 10


def test_refund_restocks_and_cannot_repeat(alpha, app, two_tenants, gateway):
    http = gateway(CHARGED, FakeResp(200, {"transactionOperationStatus": "Refunded", "responseCode": "00"}))
    sell(alpha, two_tenants, quantity=2, method="ecocash", phone="0773047653")
    with app.app_context():
        sid = Sale.query.one().id
    alpha.post(f"/t/alpha/app/sales/{sid}/refund")
    body = http.calls[1][2]
    assert body["tranType"] == "REF" and body["originalEcocashReference"] == "MP1.T1"
    with app.app_context():
        s = Sale.query.one()
        assert (s.payment_status, s.paid) == ("refunded", 0)
        assert db.session.get(Product, two_tenants["alpha"]["product"]).stock == 10
    assert alpha.post(f"/t/alpha/app/sales/{sid}/refund").status_code == 404


def test_onemoney_records_reference(alpha, app, two_tenants):
    assert "OneMoney number" in sell(alpha, two_tenants, quantity=1, method="onemoney", phone="0773047653").json["error"]
    assert "transaction code" in sell(alpha, two_tenants, quantity=1, method="onemoney", phone="0711234567").json["error"]
    r = sell(alpha, two_tenants, quantity=1, method="onemoney", phone="0711234567", payment_ref="NM123")
    assert r.status_code == 200
    with app.app_context():
        s = Sale.query.one()
        assert (s.payment_method, s.payment_ref, s.paid) == ("onemoney", "NM123", s.total)


def test_tenant_credentials_encrypted_and_isolated(client, app, two_tenants):
    from app.models import Tenant, TenantPayment
    from app.payments import client_for_tenant

    login(client, "alpha", two_tenants["alpha"]["email"])
    form = {"ecocash_enabled": "on", "username": "alpha-user", "password": "s3cret-pw", "merchant_code": "001",
            "merchant_pin": "4321", "merchant_number": "+263 78 873 2685"}
    client.post("/t/alpha/app/payments", data=form)
    with app.app_context():
        tp = TenantPayment.query.one()
        assert tp.ecocash_enabled and tp.merchant_number == "788732685"
        assert "s3cret-pw" not in tp.password_enc and "4321" not in tp.merchant_pin_enc
        s = app.extensions["settings"]
        c = client_for_tenant(s, db.session.get(Tenant, two_tenants["alpha"]["tenant"]))
        assert c.enabled and (c.s.ecocash_password, c.s.ecocash_merchant_pin) == ("s3cret-pw", "4321")
        # beta has nothing configured and must not inherit alpha's account
        assert not client_for_tenant(s, db.session.get(Tenant, two_tenants["beta"]["tenant"])).enabled
    # blank secrets on re-save keep the stored ones
    client.post("/t/alpha/app/payments", data={**form, "password": "", "merchant_pin": "", "username": "new"})
    with app.app_context():
        c = client_for_tenant(app.extensions["settings"], db.session.get(Tenant, two_tenants["alpha"]["tenant"]))
        assert c.s.ecocash_username == "new" and c.s.ecocash_password == "s3cret-pw"


def test_cannot_enable_incomplete_and_staff_blocked(client, app, two_tenants):
    from app.models import TenantPayment

    login(client, "alpha", two_tenants["alpha"]["email"])
    client.post("/t/alpha/app/payments", data={"ecocash_enabled": "on", "username": "x"})
    with app.app_context():
        assert not TenantPayment.query.one().ecocash_enabled
    client.get("/logout")
    assert client.get("/t/beta/app/payments").status_code in (302, 404)
