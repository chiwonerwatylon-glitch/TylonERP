from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import db
from app.models import Sale
from app.services.matching import is_valid_signature, rank_matches, signature_score
from app.services.parsing import integer, money
from app.services.sales import open_credit_sales, sale_totals
from app.services.theme import accent_css, auth_palette, luminance, mix, rgb

SIG_A = "0" * 16 + "80" * 27
SIG_B = "f" * 16 + "00" * 27


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "-0.01", "", "abc", None])
def test_money_rejects_unusable_values(raw):
    assert money(raw) is None


def test_money_accepts_zero_and_decimals():
    assert money("0") == 0 and money(" 3.50 ") == Decimal("3.50")


def test_integer_edge_cases():
    assert integer("0") == 0 and integer(None, 9) == 9 and integer("1.5") is None


# ---------------------------------------------------------------- matching

def test_signature_validation():
    assert is_valid_signature(SIG_A)
    assert not is_valid_signature(SIG_B.upper()) and not is_valid_signature(SIG_A[:-1]) and not is_valid_signature(None)


def test_rank_matches_orders_and_cuts_off():
    near = SimpleNamespace(name="near", signature=SIG_A)
    far = SimpleNamespace(name="far", signature=SIG_B)
    none = SimpleNamespace(name="none", signature=None)
    ranked = rank_matches(SIG_A, [far, none, near])
    assert [p.name for _, p in ranked] == ["near"]
    assert ranked[0][0] == 0
    both = rank_matches(SIG_A, [far, near], cutoff=1.1)
    assert [p.name for _, p in both] == ["near", "far"]
    assert len(rank_matches(SIG_A, [near] * 10, limit=3)) == 3
    assert signature_score(SIG_A, SIG_B) > 0.45


# ---------------------------------------------------------------- theme

def test_mix_and_rgb():
    assert mix("#000000", "#ffffff", 0) == "#000000" and mix("#000000", "#ffffff", 1) == "#ffffff"
    assert rgb("#0a66c2") == "10,102,194"


def test_accent_css_picks_readable_text_colour():
    assert accent_css("") == "" and accent_css(None) == ""
    assert "--on-primary:#ffffff" in accent_css("#0a66c2")  # dark accent, white text
    assert "--on-primary:#10131c" in accent_css("#ffe066")  # light accent, dark text
    assert luminance("#ffe066") > 0.6


def test_auth_palette():
    assert auth_palette(None, None) is None
    light = auth_palette("#f4f2ee", "#ffffff")
    assert light["mode"] == "light" and light["text"] == "#161b2e"
    dark = auth_palette("#101010", None)  # panel falls back to background
    assert dark["mode"] == "dark" and dark["panel"] == "#101010"


# ---------------------------------------------------------------- sales totals in SQL

@pytest.fixture
def ledger(app, two_tenants):
    """alpha: cash 20, credit 10 (paid 0), part-paid 15 (paid 5), old cash 100; beta: one sale that must not leak in."""
    now = datetime.utcnow()
    with app.app_context():
        a, b = two_tenants["alpha"], two_tenants["beta"]

        def sale(owner, qty, price, paid, age_days=0, client=True):
            db.session.add(Sale(
                tenant_id=owner["tenant"], client_id=owner["client"] if client else None, product_id=owner["product"],
                product_name="x", quantity=qty, unit_price=Decimal(price), paid=Decimal(paid),
                created_at=now - timedelta(days=age_days)))

        sale(a, 2, "10", "20")
        sale(a, 1, "10", "0")
        sale(a, 3, "5", "5")
        sale(a, 1, "100", "100", age_days=60)
        sale(a, 1, "7", "0", client=False)  # credit with no client: counted in totals, never listed as a debtor
        sale(b, 9, "9", "0")
        db.session.commit()
    return two_tenants


def test_totals_match_a_python_sum(app, ledger):
    with app.app_context():
        tid = ledger["alpha"]["tenant"]
        sales = Sale.query.filter_by(tenant_id=tid).all()
        t = sale_totals(db.session, tid)
        assert t["count"] == len(sales)
        assert t["total"] == sum((s.total for s in sales), Decimal(0))
        assert t["paid"] == sum((s.paid for s in sales), Decimal(0))
        assert t["owed"] == sum((s.balance for s in sales), Decimal(0)) == Decimal(27)


def test_totals_filter_by_date_and_kind(app, ledger):
    with app.app_context():
        tid = ledger["alpha"]["tenant"]
        recent = sale_totals(db.session, tid, since=datetime.utcnow() - timedelta(days=30))
        assert recent["total"] == Decimal(52) and recent["count"] == 4
        assert sale_totals(db.session, tid, kind="cash")["count"] == 2
        assert sale_totals(db.session, tid, kind="credit")["count"] == 3


def test_totals_of_an_empty_tenant_are_zero(app, ledger):
    with app.app_context():
        t = sale_totals(db.session, 9999)
        assert t == {"count": 0, "total": Decimal(0), "paid": Decimal(0), "owed": Decimal(0)}


def test_open_credit_sales_only_lists_debts_with_a_client(app, ledger):
    with app.app_context():
        rows = open_credit_sales(ledger["alpha"]["tenant"])
        assert sorted(s.balance for s in rows) == [Decimal(10), Decimal(10)]
        assert all(s.client_id for s in rows)


def test_pages_show_the_sql_totals(client, ledger):
    from .conftest import login
    login(client, "alpha", ledger["alpha"]["email"])
    home = client.get("/t/alpha/app/").data
    assert b"52.00" in home and b"27.00" in home  # revenue last 30 days, owed
    assert b"27.00" in client.get("/t/alpha/app/sales").data
    assert b"20.00" in client.get("/t/alpha/app/debtors").data
    credit = client.get("/t/alpha/app/sales?type=credit").data
    assert b"27.00" in credit


