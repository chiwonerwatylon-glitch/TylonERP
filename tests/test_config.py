import pytest

from app.config import INSECURE_DEFAULT_KEY, Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults_are_development():
    s = make()
    assert not s.is_production and s.cookie_secure is True
    assert s.validate_for_runtime() == []


def test_postgres_scheme_is_normalised():
    assert make(database_url="postgres://u:p@h/db").database_url == "postgresql://u:p@h/db"
    assert make(database_url="postgresql://u:p@h/db").database_url == "postgresql://u:p@h/db"


def test_production_refuses_the_dev_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        make(env="production").validate_for_runtime()


def test_railway_counts_as_production():
    s = make(railway_environment="production")
    assert s.is_production
    with pytest.raises(RuntimeError):
        s.validate_for_runtime()


def test_production_warnings():
    s = make(env="production", secret_key="short", cookie_secure=False)
    text = " ".join(s.validate_for_runtime())
    assert "32 characters" in text and "SQLite" in text and "COOKIE_SECURE" in text


def test_strong_production_config_is_quiet():
    s = make(env="production", secret_key="x" * 40, database_url="postgresql://u:p@h/db")
    assert s.validate_for_runtime() == []
    assert s.secret_key != INSECURE_DEFAULT_KEY


def test_bad_pool_size_rejected():
    with pytest.raises(ValueError):
        make(db_pool_size=0)


def test_app_refuses_to_boot_with_dev_key_in_production(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'x.db'}")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()
