import pytest

from app import create_app

from .conftest import login


def test_security_headers_on_every_page(client):
    r = client.get("/login")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "camera=(self)" in r.headers["Permissions-Policy"]


def test_pages_are_not_cached(client):
    assert client.get("/login").headers["Cache-Control"] == "no-store"


def test_static_files_stay_cacheable(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200 and r.headers.get("Cache-Control") != "no-store"


def test_hsts_only_over_https(app):
    app.config["SESSION_COOKIE_SECURE"] = True
    c = app.test_client()
    assert "Strict-Transport-Security" not in c.get("/login").headers
    r = c.get("/login", base_url="https://localhost")
    assert "max-age=31536000" in r.headers["Strict-Transport-Security"]


def test_unknown_email_and_wrong_password_look_identical(client, two_tenants):
    a = login(client, "alpha", "nobody@alpha.test", "x")
    b = login(client, "alpha", two_tenants["alpha"]["email"], "wrong")
    assert b"Incorrect email or password" in a.data and b"Incorrect email or password" in b.data


@pytest.fixture
def limited(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rl.db'}")
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3 per minute")
    monkeypatch.setenv("RATELIMIT_ENABLED", "1")
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def test_login_is_rate_limited_per_ip(limited):
    codes = [limited.post("/login", data={"email": "a@b.co", "password": "x"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_rate_limit_does_not_block_page_views(limited):
    for _ in range(6):
        assert limited.get("/login").status_code == 200
