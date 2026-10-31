import pytest

from app import create_app, db
from app.models import Client, Product, Tenant, User


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """scrypt is deliberately slow; tests use a cheap hash."""
    from werkzeug.security import generate_password_hash

    monkeypatch.setattr("app.models.generate_password_hash",
                        lambda pw: generate_password_hash(pw, method="pbkdf2:sha256:1000"))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def make_tenant(slug, plan="starter", password="pw-12345678"):
    t = Tenant(name=slug.title(), slug=slug, contact_email=f"owner@{slug}.test", plan=plan)
    u = User(tenant=t, email=f"owner@{slug}.test", name="Owner", role="admin")
    u.set_password(password)
    db.session.add_all([t, u])
    db.session.commit()
    return t, u


@pytest.fixture
def two_tenants(app):
    """Tenant A and B, each with an admin and one product and one client."""
    out = {}
    with app.app_context():
        for slug in ("alpha", "beta"):
            t, u = make_tenant(slug)
            p = Product(tenant_id=t.id, name=f"{slug} soap", price=5, stock=10, barcode=f"{slug}-1")
            c = Client(tenant_id=t.id, name=f"{slug} client")
            db.session.add_all([p, c])
            db.session.commit()
            out[slug] = {"tenant": t.id, "email": u.email, "product": p.id, "client": c.id}
    return out


def login(client, slug, email, password="pw-12345678"):
    return client.post(f"/t/{slug}", data={"email": email, "password": password})
