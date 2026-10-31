"""The baseline migration must build the schema from scratch and upgrade a database from an older release."""
import pytest
import sqlalchemy as sa
from flask_migrate import downgrade, upgrade

from app import MIGRATIONS_DIR, create_app, db


@pytest.fixture
def bare_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("AUTO_MIGRATE", "0")
    monkeypatch.setenv("RATELIMIT_ENABLED", "0")
    app = create_app()
    yield app
    with app.app_context():
        db.engine.dispose()


def tables(app):
    with app.app_context():
        return set(sa.inspect(db.engine).get_table_names())


def test_app_starts_without_schema_when_auto_migrate_is_off(bare_app):
    assert tables(bare_app) <= {"alembic_version"}
    assert bare_app.test_client().get("/login").status_code == 200


def test_upgrade_builds_the_full_schema(bare_app):
    with bare_app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    assert {"tenants", "users", "products", "clients", "sales", "tenant_branding"} <= tables(bare_app)


def test_upgrade_matches_the_models(bare_app):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with bare_app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        with db.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert diff == []


def test_upgrade_twice_is_a_no_op(bare_app):
    with bare_app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        upgrade(directory=MIGRATIONS_DIR)


def test_downgrade_removes_the_schema(bare_app):
    with bare_app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        downgrade(directory=MIGRATIONS_DIR, revision="base")
    assert tables(bare_app) <= {"alembic_version"}


def test_legacy_database_is_adopted_without_losing_data(bare_app):
    """A production database made by create_all in an older release: old shape, real rows, no alembic table."""
    with bare_app.app_context():
        with db.engine.begin() as conn:
            conn.execute(sa.text(
                "CREATE TABLE tenants (id INTEGER PRIMARY KEY, name VARCHAR(150) NOT NULL, slug VARCHAR(60) NOT NULL,"
                " contact_email VARCHAR(255) NOT NULL, plan VARCHAR(20) NOT NULL, is_active BOOLEAN NOT NULL,"
                " created_at DATETIME NOT NULL)"))
            conn.execute(sa.text(
                "INSERT INTO tenants (name, slug, contact_email, plan, is_active, created_at)"
                " VALUES ('Old Co', 'old', 'o@old.test', 'starter', 1, '2024-01-01')"))
        upgrade(directory=MIGRATIONS_DIR)
        insp = sa.inspect(db.engine)
        cols = {c["name"] for c in insp.get_columns("tenants")}
        assert {"phone", "trial_ends_at"} <= cols  # added to the existing table
        assert "users" in insp.get_table_names()  # created next to it
        row = db.session.execute(sa.text("SELECT name, slug FROM tenants")).one()
        assert tuple(row) == ("Old Co", "old")


def test_auto_migrate_on_by_default_for_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.delenv("AUTO_MIGRATE", raising=False)
    monkeypatch.setenv("RATELIMIT_ENABLED", "0")
    app = create_app()
    assert "users" in tables(app)
    with app.app_context():
        db.engine.dispose()


def test_seed_admin_command(bare_app):
    with bare_app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    bare_app.extensions["settings"].admin_password = "cli-pass-123"
    result = bare_app.test_cli_runner().invoke(args=["seed-admin"])
    assert result.exit_code == 0 and "Administrator checked" in result.output
    with bare_app.app_context():
        from app.models import User
        assert User.query.filter_by(role="superadmin").count() == 1
