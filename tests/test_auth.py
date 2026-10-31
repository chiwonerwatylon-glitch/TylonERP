import pytest

from app import db
from app.models import User

from .conftest import login


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_root_redirects_to_login(client):
    assert client.get("/").headers["Location"].endswith("/login")


def test_admin_seeded_and_can_sign_in(client):
    r = client.post("/login", data={"email": "admin@erp.co.zw", "password": "admin-pass-123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/")


def test_workspace_requires_login(client, two_tenants):
    r = client.get("/t/alpha/app/")
    assert r.status_code == 302 and "/t/alpha" in r.headers["Location"]


def test_wrong_password_rejected(client, two_tenants):
    r = login(client, "alpha", two_tenants["alpha"]["email"], "nope")
    assert r.status_code == 200 and b"Incorrect email or password" in r.data


def test_account_locks_after_five_failures(client, app, two_tenants):
    for _ in range(5):
        login(client, "alpha", two_tenants["alpha"]["email"], "nope")
    r = login(client, "alpha", two_tenants["alpha"]["email"])  # correct password, now locked
    # Same message as a wrong password, so a lockout does not reveal that the account exists
    assert b"Incorrect email or password" in r.data
    assert client.get("/t/alpha/app/").status_code == 302
    with app.app_context():
        assert User.query.filter_by(email=two_tenants["alpha"]["email"]).one().is_locked()


def test_cannot_sign_in_on_another_tenants_page(client, two_tenants):
    r = login(client, "beta", two_tenants["alpha"]["email"])
    assert r.status_code == 200 and b"Incorrect email or password" in r.data


def test_login_next_cannot_leave_site(client, two_tenants):
    email = two_tenants["alpha"]["email"]
    r = client.post("/t/alpha?next=//evil.com", data={"email": email, "password": "pw-12345678"})
    assert r.status_code == 302 and "evil.com" not in r.headers["Location"]


def test_superadmin_area_forbidden_to_tenant_user(client, two_tenants):
    login(client, "alpha", two_tenants["alpha"]["email"])
    # The tenant cookie is not sent to /admin, so the visitor is anonymous there
    r = client.get("/admin/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_tenant_user_forced_onto_admin_cookie_is_forbidden(client, app, two_tenants):
    # A tenant user who somehow reaches /admin with a session (same cookie name) gets 403
    from flask_login import login_user

    from app.routes import superadmin_required
    with app.test_request_context("/admin/"):
        login_user(db.session.get(User, 2))
        with pytest.raises(Exception) as exc:
            superadmin_required(lambda: "ok")()
        assert exc.value.code == 403


def test_inactive_tenant_cannot_sign_in(client, app, two_tenants):
    from app.models import Tenant
    with app.app_context():
        db.session.get(Tenant, two_tenants["alpha"]["tenant"]).is_active = False
        db.session.commit()
    r = login(client, "alpha", two_tenants["alpha"]["email"])
    assert r.status_code == 200 and b"disabled" in r.data
